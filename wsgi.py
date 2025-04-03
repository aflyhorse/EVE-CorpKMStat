from kmstat import app

if __name__ == '__main__':
    app.run()

# Example Usage:
# killall gunicorn ; sleep 1 ; \
# nohup gunicorn --bind 127.0.0.1:8000 --workers 2 wsgi:app &>> instance/flask-$(date --iso-8601).log &
