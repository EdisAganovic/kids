/*
  An example showing rainbow colours on a 3.5" TFT LCD screen
  and to show a basic example of font use.

  Make sure all the display driver and pin connections are correct by
  editing the User_Setup.h file in the TFT_eSPI library folder.

  Note that yield() or delay(0) must be called in long duration for/while
  loops to stop the ESP8266 watchdog triggering.

  #########################################################################
  ###### DON'T FORGET TO UPDATE THE User_Setup.h FILE IN THE LIBRARY ######
  #########################################################################
*/

#include <TFT_eSPI.h>  // Graphics and font library for ST7735 driver chip
#include <SPI.h>
#include <WiFi.h>
#include <HTTPClient.h>
#include <ArduinoJson.h>  // For JSON parsing

// WiFi credentials - change these to your network
const char* ssid = "Dershana";
const char* password = "palacinke";

#define PURPLE 0xF81F  // your background purple

TFT_eSPI tft = TFT_eSPI();  // Invoke library, pins defined in User_Setup.h

unsigned long targetTime = 0;
byte red = 31;
byte green = 0;
byte blue = 0;
byte state = 0;
unsigned int colour = red << 11;

// Variables for WiFi connection
unsigned long lastWiFiCheck = 0;
const unsigned long wifiCheckInterval = 10000;  // Check connection every 10 seconds
bool wifiConnected = false;

// Variables for receiving kids data from server
String activeKidName = "No active session";
String timeRemaining = "";
unsigned long lastKidsCheck = 0;
const unsigned long kidsCheckInterval = 2000;  // Check for kids data every 2 seconds
unsigned long lastErrorDisplay = 0;
const unsigned long errorDisplayInterval = 20000;        // Display error messages every 20 seconds
String serverURL = "http://192.168.0.111:8000/api/active-session";  // API endpoint for active session data

// Function to update for the next kid when time expires
void updateForNextKid();

// Function to redraw all text elements on the screen
void redrawAllText() {
  // Clear text areas - draw black rectangles to cover previous text
  tft.fillRect(0, 80, 320, 40, TFT_BLACK);   // For active kid name (font 4)
  tft.fillRect(0, 160, 320, 60, TFT_BLACK);  // For time remaining value (font 6)

  // Display updated text
  tft.setTextColor(TFT_WHITE);
  tft.drawCentreString(activeKidName.c_str(), 160, 80, 4);
  
  // Only display time if there's an active session
  if (activeKidName != "No active session") {
    tft.drawCentreString(timeRemaining.c_str(), 160, 160, 6);
  } else {
    // Display "No active session" message instead of time
    tft.drawCentreString("No active session", 160, 160, 4);
  }
}

void connectToWiFi() {
  if (WiFi.status() != WL_CONNECTED) {
    Serial.print("Connecting to ");
    Serial.println(ssid);
    WiFi.begin(ssid, password);

    int attempts = 0;
    while (WiFi.status() != WL_CONNECTED && attempts < 20) {
      delay(500);
      Serial.print(".");
      attempts++;
    }

    if (WiFi.status() == WL_CONNECTED) {
      Serial.println("");
      Serial.println("WiFi connected!");
      Serial.print("IP address: ");
      Serial.println(WiFi.localIP());
      wifiConnected = true;
    } else {
      Serial.println("");
      Serial.println("WiFi connection failed!");
      wifiConnected = false;
    }
  }
}

String getActiveSessionData() {
  if (WiFi.status() == WL_CONNECTED) {
    HTTPClient http;
    http.begin(serverURL);

    int httpResponseCode = http.GET();

    if (httpResponseCode > 0) {
      String response = http.getString();
      http.end();

      // Parse the JSON response
      StaticJsonDocument<500> doc;
      DeserializationError error = deserializeJson(doc, response);

      if (error == DeserializationError::Ok) {
        // Check if there's an active session
        bool isActive = doc["is_active"];
        if (isActive) {
          // Get active kid information
          String kidName = doc["active_kid"]["name"].as<String>();
          double timeRemainingSeconds = doc["active_kid"]["time_remaining_seconds"];
          
          // Update the display variables
          activeKidName = kidName;
          
          // Convert seconds to MM:SS format
          int totalSeconds = (int)timeRemainingSeconds;
          int minutes = abs(totalSeconds) / 60;
          int seconds = abs(totalSeconds) % 60;
          timeRemaining = String(minutes) + ":" + (seconds < 10 ? "0" : "") + String(seconds);
          
          // Add negative sign if time is negative (bonus time being used)
          if (timeRemainingSeconds < 0) {
            timeRemaining = "-" + timeRemaining;
          }
          
          // Check if time has reached zero or gone negative
          // Only trigger update if we just transitioned from positive to non-positive time
          static bool wasPositiveTime = true;
          if (wasPositiveTime && totalSeconds <= 0) {
            wasPositiveTime = false;
            // Time has expired, update for next kid
            updateForNextKid();
          } else if (totalSeconds > 0) {
            wasPositiveTime = true;
          }
        } else {
          // No active session
          activeKidName = "No active session";
          timeRemaining = "";
        }

        // Redraw all text elements on the screen
        redrawAllText();

        // Return the active kid name for compatibility
        return activeKidName;
      } else {
        // Only show JSON parsing error every 20 seconds to reduce spam
        if (millis() - lastErrorDisplay >= errorDisplayInterval) {
          Serial.println("JSON parsing failed!");
          lastErrorDisplay = millis();
        }
        return "";
      }
    } else {
      // Only show HTTP error every 20 seconds to reduce spam
      if (millis() - lastErrorDisplay >= errorDisplayInterval) {
        Serial.print("Error on HTTP request: ");
        Serial.println(httpResponseCode);
        lastErrorDisplay = millis();
      }
      http.end();
      return "";
    }
  }
  return "";
}

// Function to update for the next kid when time expires
void updateForNextKid() {
  if (WiFi.status() == WL_CONNECTED) {
    HTTPClient http;
    // Use the same server URL but with POST to indicate time expiration
    String updateURL = serverURL + "/time-expired";  // This endpoint should handle time expiration on the server
    http.begin(updateURL);
    http.addHeader("Content-Type", "application/json");

    // Send a simple POST request to indicate time has expired
    String payload = "{}";
    int httpResponseCode = http.POST(payload);

    if (httpResponseCode > 0) {
      Serial.println("Time expired notification sent successfully");
    } else {
      Serial.print("Error sending time expired notification: ");
      Serial.println(httpResponseCode);
    }
    
    http.end();
  }
}

void setup(void) {
  Serial.begin(9600);  // Changed from 115200 to 9600 for better compatibility

  tft.init();
  tft.setRotation(1);
  tft.fillScreen(TFT_BLACK);  // black background

  // Display initial text using variables
  tft.setTextColor(TFT_WHITE);
  tft.drawCentreString(activeKidName.c_str(), 160, 80, 4);
  
  // Check if there's an active session to determine what to display
  if (activeKidName != "No active session") {
    tft.drawCentreString(timeRemaining.c_str(), 160, 160, 6);
  } else {
    tft.drawCentreString("No active session", 160, 160, 4);
  }

  // Connect to WiFi
  connectToWiFi();
}

void loop() {
  // Handle WiFi reconnection if needed
  if (millis() - lastWiFiCheck >= wifiCheckInterval) {
    if (WiFi.status() != WL_CONNECTED) {
      connectToWiFi();
    }
    lastWiFiCheck = millis();
  }

  // Check for active session data from server
  if (millis() - lastKidsCheck >= kidsCheckInterval && wifiConnected) {
    String newActiveKid = getActiveSessionData();
    lastKidsCheck = millis();
  }
}
