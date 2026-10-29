ARG BUILD_FROM
FROM $BUILD_FROM
RUN apk add --no-cache python3 py3-flask py3-requests py3-gunicorn
COPY app.py run.sh logo.png /app/
RUN chmod a+x /app/run.sh
CMD ["/app/run.sh"]
