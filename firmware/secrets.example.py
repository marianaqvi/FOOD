# firmware/secrets.example.py
# TEMPLATE ONLY. Copy to firmware/secrets.py (git-ignored) or, better, run:
#     python3 scripts/make_secrets.py
# which asks for the Wi-Fi name and password in your terminal and fills in the rest.
# Never commit secrets.py. It is uploaded to the board as /secrets.py by scripts/deploy_board.py.

WIFI_SSID = "your-wifi-name"
WIFI_PASSWORD = "your-wifi-password"

# The Mac's LAN IP address (not "localhost": the board is a different machine). Use an IP, not a
# hostname, so no DNS lookup can block. Temporary plain HTTP, trusted LAN and test data only.
SERVER_HOST = "192.168.0.10"
SERVER_PORT = 3000

# The device token. In mock mode the server creates one at web/.data/dev-device-token.
DEVICE_TOKEN = "paste-the-device-token-here"
