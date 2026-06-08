import network
import time
import dht
import gc
import uasyncio as asyncio
from machine import Pin, ADC
import umail

# ==================== CONFIGURATION ====================
WIFI_SSID = "Your_WiFi_SSID"
WIFI_PASS = "Your_WiFi_Password"

GMAIL_USER = "your_email@gmail.com"
GMAIL_APP_PASS = "xxxx xxxx xxxx xxxx"  # 16-character Google App Password
RECIPIENT_GATEWAY = "5551234567@vtext.com"  # Carrier SMS email address

# Environmental rules
HUMIDITY_LOW_LIMIT = 30.0   # Trigger if below this %
HUMIDITY_HIGH_LIMIT = 70.0  # Trigger if above this %
CHECK_INTERVAL_SEC = 300    # 5 minutes background check

# Hardware GPIO Pin assignments
SENSOR_1_PIN = 16
SENSOR_2_PIN = 17
# =======================================================

# Initialize Hardware Objects
wlan = network.WLAN(network.STA_IF)
sensor1 = dht.DHT22(Pin(SENSOR_1_PIN))
sensor2 = dht.DHT22(Pin(SENSOR_2_PIN))
internal_temp_sensor = ADC(4)  # Built-in RP2040 temperature sensor

# Global State Tracking Variables
consecutive_failures = 0
alert_sent = False
latest_humidity = 0.0
system_status = "Initializing..."
pico_ip = "0.0.0.0"

def get_internal_temp():
    """Reads the RP2040 chip's internal temperature core."""
    try:
        reading = internal_temp_sensor.read_u16() * (3.3 / 65535)
        temperature_c = 27 - (reading - 0.706) / 0.001721
        temperature_f = (temperature_c * 9/5) + 32
        return f"{temperature_f:.1f}°F ({temperature_c:.1f}°C)"
    except:
        return "N/A"

def connect_wifi():
    """Configures the local hostname and establishes a Wi-Fi connection."""
    global pico_ip
    if wlan.isconnected():
        return True
    
    wlan.active(True)
    
    # CRITICAL: Define network identity BEFORE making the connection link
    try:
        network.hostname("picopi")
        print("Network identity registered: http://picopi.local")
    except Exception as e:
        print("Could not set hostname:", e)
    
    print("Connecting to network...")
    wlan.connect(WIFI_SSID, WIFI_PASS)
    
    timeout = 15
    while not wlan.isconnected() and timeout > 0:
        time.sleep(1)
        timeout -= 1
        
    if wlan.isconnected():
        pico_ip = wlan.ifconfig()[0]
        print("Connected! IP:", pico_ip)
        return True
    else:
        print("WiFi Connection Failed.")
        return False

def send_text_alert(message_body):
    """Pushes a brief text message via Gmail Secure SMTP over the Carrier Gateway."""
    if not wlan.isconnected():
        print("Cannot send text: No internet connection.")
        return

    try:
        print("Initializing secure SMTP tunnel...")
        smtp = umail.SMTP('://gmail.com', 465, ssl=True)
        smtp.login(GMAIL_USER, GMAIL_APP_PASS)
        smtp.to(RECIPIENT_GATEWAY)
        smtp.write(f"Subject: Pico W Alert\n\n{message_body}")
        smtp.send()
        smtp.quit()
        print("Text alert successfully delivered to carrier gateway.")
    except Exception as e:
        print("SMTP Error sending text:", e)

def read_and_sanity_check_sensor(sensor_obj, name):
    """Handles low-level hardware communication and drops raw data errors."""
    try:
        sensor_obj.measure()
        h = sensor_obj.humidity()
        t = sensor_obj.temperature()
        if h < 0.0 or h > 100.0 or t < -40.0 or t > 80.0:
            return None
        return h
    except OSError:
        return None

# --- Background Task: Read Sensors Every 5 Minutes ---
async def environment_monitor_loop():
    global consecutive_failures, alert_sent, latest_humidity, system_status
    
    print("Background environmental monitor task started.")
    while True:
        # Give DHT22 sensors a brief moment to settle down
        await asyncio.sleep(2)
        h1 = read_and_sanity_check_sensor(sensor1, "Sensor 1")
        
        await asyncio.sleep(2)
        h2 = read_and_sanity_check_sensor(sensor2, "Sensor 2")
        
        valid_readings = [h for h in [h1, h2] if h is not None]
        
        if not valid_readings:
            print("Hardware Warning: Both sensors produced broken metrics.")
            system_status = "Sensor Hardware Error"
        else:
            latest_humidity = sum(valid_readings) / len(valid_readings)
            print(f"Periodic Check - Combined Humidity: {latest_humidity:.1f}%")
            
            # Check against target boundaries
            if latest_humidity < HUMIDITY_LOW_LIMIT or latest_humidity > HUMIDITY_HIGH_LIMIT:
                consecutive_failures += 1
                system_status = f"Out of Bounds (Strike {consecutive_failures}/3)"
                
                if consecutive_failures >= 3:
                    system_status = "CRITICAL: Alert Dispatched"
                    if not alert_sent:
                        alert_msg = f"Humidity Alert! Value has breached safe limits. Current: {latest_humidity:.1f}%"
                        send_text_alert(alert_msg)
                        alert_sent = True
            else:
                # System is verified safe -> AUTOMATIC RESET clears metrics
                consecutive_failures = 0
                alert_sent = False
                system_status = "System Status: OK"
                
        # Non-blocking pause allows the web server to handle traffic during the 5 minutes
        await asyncio.sleep(CHECK_INTERVAL_SEC)

# --- Web Server Component: Serves the Webpage ---
async def handle_client(reader, writer):
    global latest_humidity, system_status, pico_ip
    
    # Read the incoming browser HTTP request header
    await reader.read(1024)
    
    # Force run garbage collection to keep small RAM space clean
    gc.collect()
    free_mem = gc.mem_free()
    pico_internal_temp = get_internal_temp()
    
    # Determine CSS styling color based on status layout
    status_color = "#2ecc71" if "OK" in system_status else "#e74c3c"
    if "Initializing" in system_status:
        status_color = "#f39c12"

    # Minimalist, clean HTML string designed to look great on phones
    html = f"""HTTP/1.1 200 OK\r
Content-Type: text/html\r
Connection: close\r
\r
<!DOCTYPE html>
<html>
<head>
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <title>Pico W Monitor</title>
    <style>
        body {{ font-family: -apple-system, sans-serif; background: #f4f6f9; margin: 20px; color: #333; }}
        .card {{ background: white; padding: 24px; border-radius: 12px; box-shadow: 0 4px 6px rgba(0,0,0,0.05); max-width: 400px; margin: 0 auto; }}
        h2 {{ margin-top: 0; color: #2c3e50; text-align: center; }}
        .status {{ font-weight: bold; font-size: 1.2em; text-align: center; color: white; padding: 10px; border-radius: 6px; margin: 15px 0; background: {status_color}; }}
        .metric {{ font-size: 2.2em; text-align: center; font-weight: bold; margin: 20px 0; color: #2c3e50; }}
        .tech-box {{ background: #eceff1; padding: 14px; border-radius: 6px; font-size: 0.85em; color: #546e7a; line-height: 1.6; margin-top: 20px; }}
        .tech-title {{ font-weight: bold; color: #37474f; margin-bottom: 5px; border-bottom: 1px solid #cfd8dc; padding-bottom: 3px; }}
    </style>
</head>
<body>
    <div class="card">
        <h2>Pico W Environment</h2>
        <div class="status">{system_status}</div>
        <div class="metric">{latest_humidity:.1f}% <span style="font-size:0.4em; font-weight:normal;">RH</span></div>
        
        <div class="tech-box">
            <div class="tech-title">Diagnostic Information</div>
            <b>Host Address:</b> http://picopi.local<br>
            <b>Local Network IP:</b> {pico_ip}<br>
            <b>Core Internal Temp:</b> {pico_internal_temp}<br>
            <b>Free System Memory:</b> {free_mem} Bytes
        </div>
    </div>
</body>
</html>
"""
    try:
        writer.write(html)
        await writer.drain()
    except Exception as e:
        print("Web server write error:", e)
    finally:
        await writer.close()
        await writer.wait_closed()

# --- Orchestrate Program Bootloader Execution ---
async def main():
    # 1. Spin up internet connectivity first
    if not connect_wifi():
        print("Fatal: Could not establish network connectivity. Halting application setup.")
        return
        
    # 2. Start the local background web server socket listening on standard Port 80
    print("Spinning up local HTTP server cluster on port 80...")
    await asyncio.start_server(handle_client, "0.0.0.0", 80)
    
    # 3. Chain run the background environmental sampling loop alongside the server
    await environment_monitor_loop()

# Boot the main asynchronous event driver engine
try:
    asyncio.run(main())
except KeyboardInterrupt:
    print("Application manually terminated by operator interaction.")
