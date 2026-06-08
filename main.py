import network
import time
import dht
from machine import Pin
import umail

# ==================== CONFIGURATION ====================
WIFI_SSID = "Your_WiFi_SSID"
WIFI_PASS = "Your_WiFi_Password"

GMAIL_USER = "your_email@gmail.com"
GMAIL_APP_PASS = "xxxx xxxx xxxx xxxx"  # 16-character Google App Password

# Replace with your phone number and your specific carrier's domain
# (e.g., Verizon: @vtext.com | AT&T: @txt.att.net | T-Mobile: @tmomail.net)
RECIPIENT_GATEWAY = "5551234567@vtext.com" 

# Environmental rules
HUMIDITY_LOW_LIMIT = 30.0   # Trigger alert if below this %
HUMIDITY_HIGH_LIMIT = 70.0  # Trigger alert if above this %
CHECK_INTERVAL_SEC = 300    # 5 minutes = 300 seconds

# Hardware GPIO Pin assignments
SENSOR_1_PIN = 16
SENSOR_2_PIN = 17
# =======================================================

# Initialize Hardware Objects
wlan = network.WLAN(network.STA_IF)
sensor1 = dht.DHT22(Pin(SENSOR_1_PIN))
sensor2 = dht.DHT22(Pin(SENSOR_2_PIN))

# State Tracking Variables
consecutive_failures = 0
alert_sent = False

def connect_wifi():
    """Connects to local WiFi. Returns True if successful."""
    if wlan.isconnected():
        return True
    
    print("Connecting to network...")
    wlan.active(True)
    wlan.connect(WIFI_SSID, WIFI_PASS)
    
    timeout = 15
    while not wlan.isconnected() and timeout > 0:
        time.sleep(1)
        timeout -= 1
        
    if wlan.isconnected():
        print("Connected! IP:", wlan.ifconfig())
        return True
    else:
        print("WiFi Connection Failed.")
        return False

def send_text_alert(message_body):
    """Pushes a brief text message via Gmail Secure SMTP over the Carrier Gateway."""
    if not connect_wifi():
        print("Cannot send text: No internet connection.")
        return

    try:
        print("Initializing secure SMTP tunnel...")
        # Port 465 is required for Gmail SSL
        smtp = umail.SMTP('://gmail.com', 465, ssl=True)
        smtp.login(GMAIL_USER, GMAIL_APP_PASS)
        
        smtp.to(RECIPIENT_GATEWAY)
        # Keep character count brief to avoid carrier truncation
        smtp.write(f"Subject: Pico W Alert\n\n{message_body}")
        smtp.send()
        smtp.quit()
        print("Text alert successfully delivered to carrier gateway.")
    except Exception as e:
        print("SMTP Error sending text:", e)

def read_and_sanity_check_sensor(sensor_obj, name):
    """Handles low-level hardware communication and drops raw data errors."""
    try:
        # DHT22 requires a 2-second recovery delay before a fresh query
        time.sleep(2) 
        sensor_obj.measure()
        h = sensor_obj.humidity()
        t = sensor_obj.temperature()
        
        # Physics filter: Ignore raw readings completely outside sensor specs
        if h < 0.0 or h > 100.0 or t < -40.0 or t > 80.0:
            print(f"[{name}] Hardware read out of physical bounds. Discarding sample.")
            return None
        return h
    except OSError:
        print(f"[{name}] Communication timing failed. Sensor timed out.")
        return None

# --- Main System Loop ---
print("Application initiated. Beginning observation loop...")

while True:
    print("\n--- Starting Scheduled Environment Evaluation ---")
    
    # Read both sensors independently
    h1 = read_and_sanity_check_sensor(sensor1, "Sensor 1 (GP16)")
    h2 = read_and_sanity_check_sensor(sensor2, "Sensor 2 (GP17)")
    
    # Filter out any failed data points
    valid_readings = [h for h in [h1, h2] if h is not None]
    
    if not valid_readings:
        print("Warning: Both sensors produced missing or broken data this cycle.")
        # We skip tracking or modifying variables to avoid false alarms from dead hardware
    else:
        # Calculate balanced average of operational sensors
        avg_humidity = sum(valid_readings) / len(valid_readings)
        print(f"Current System Consolidated Humidity: {avg_humidity:.1f}%")
        
        # Check against target limits
        if avg_humidity < HUMIDITY_LOW_LIMIT or avg_humidity > HUMIDITY_HIGH_LIMIT:
            consecutive_failures += 1
            print(f"CRITICAL: Humidity out of limits! Tally sequence: {consecutive_failures}/3")
            
            # 3 strikes reached: time to alert
            if consecutive_failures >= 3:
                if not alert_sent:
                    alert_msg = f"Humidity Alert! Value has breached safe range 3 times consecutively. Current: {avg_humidity:.1f}%"
                    send_text_alert(alert_msg)
                    alert_sent = True  # Locks the email engine to prevent repeating texts
                else:
                    print("Humidity is still out of bounds, but text was already sent. Standing by.")
        else:
            # Environment is completely safe
            if consecutive_failures > 0 or alert_sent:
                print("Environment recovered within safe operational margins. Resetting tally and re-arming alert engine.")
            
            # AUTOMATIC RESET: Clean variables so system is ready for the next issue
            consecutive_failures = 0
            alert_sent = False  

    print(f"Going to sleep for {CHECK_INTERVAL_SEC} seconds...")
    time.sleep(CHECK_INTERVAL_SEC)
