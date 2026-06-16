@echo off
rem Opens a free Cloudflare tunnel to the local tape signal listener so
rem TradingView alert webhooks can reach this PC.
rem
rem 1. Make sure the listener is running (START.bat starts it automatically).
rem 2. Run this file and wait for the line that shows your public URL:
rem       https://SOMETHING.trycloudflare.com
rem 3. Paste that URL into the Webhook URL field of your TradingView alerts.
rem
rem If you started the pipeline with a custom -ListenerPort, pass the same
rem port as an argument:  TUNNEL.bat 9000   (default 8788).
rem
rem Keep this window open while trading - closing it closes the tunnel.
rem Note: the URL changes every time you restart this tunnel, so update your
rem TradingView alerts if you restart it.
set "PORT=%~1"
if "%PORT%"=="" set "PORT=8788"
cloudflared tunnel --url http://127.0.0.1:%PORT%
pause
