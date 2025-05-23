bind = "0.0.0.0:10000"
workers = 2
forwarded_allow_ips = "*"
secure_scheme_headers = {"X-Forwarded-Proto": "https"}
timeout = 600  # Longer timeout for file uploads
