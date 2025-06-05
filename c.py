from flask import Flask, Response
from prometheus_client import CollectorRegistry, generate_latest, Gauge
from azure.identity import ClientSecretCredential
from azure.mgmt.costmanagement import CostManagementClient
import datetime
import os
from dotenv import load_dotenv
import logging
import traceback

# Load environment variables from .env file
load_dotenv()

# Logging setup
logging.basicConfig(level=logging.INFO)

# Flask app
app = Flask(__name__)

# ENV VARS
TENANT_ID = os.getenv("AZURE_TENANT_ID")
CLIENT_ID = os.getenv("AZURE_CLIENT_ID")
CLIENT_SECRET = os.getenv("AZURE_CLIENT_SECRET")
SUBSCRIPTION_ID = os.getenv("AZURE_SUBSCRIPTION_ID")

# Azure auth
credential = ClientSecretCredential(
    tenant_id=TENANT_ID,
    client_id=CLIENT_ID,
    client_secret=CLIENT_SECRET
)

# Cost Management client
client = CostManagementClient(credential)

def to_iso8601(dt):
    return dt.isoformat(timespec='seconds').replace('+00:00', 'Z')

@app.route('/metrics')
def metrics():
    try:
        # Calculate date range for last 30 days (excluding today)
        end_date = datetime.date.today()  # today (excluded)
        start_date = end_date - datetime.timedelta(days=30)  # 30 days ago

        from_date = to_iso8601(datetime.datetime.combine(start_date, datetime.time.min, datetime.timezone.utc))
        to_date = to_iso8601(datetime.datetime.combine(end_date, datetime.time.min, datetime.timezone.utc))

        parameters = {
            "type": "ActualCost",
            "timeframe": "Custom",
            "timePeriod": {
                "from": from_date,
                "to": to_date
            },
            "dataset": {
                "granularity": "Daily",
                "aggregation": {
                    "totalCost": {
                        "name": "PreTaxCost",
                        "function": "Sum"
                    }
                }
            }
        }

        scope = f"/subscriptions/{SUBSCRIPTION_ID}"
        result = client.query.usage(scope=scope, parameters=parameters)
        logging.info("Azure Cost Query Result: %s", result.as_dict())

        registry = CollectorRegistry()
        gauge = Gauge('azure_30day_cumulative_cost_usd', "Azure cumulative cost over last 30 days in USD", registry=registry)

        if result.rows:
            # Sum all daily costs for cumulative 30-day cost
            total_cost = sum(float(row[0]) for row in result.rows)
            gauge.set(total_cost)
        else:
            logging.warning("No cost data returned from Azure.")

        return Response(generate_latest(registry), mimetype='text/plain')

    except Exception as e:
        logging.error("Error: %s", e)
        logging.error(traceback.format_exc())
        return Response(f"Error: {str(e)}", mimetype='text/plain', status=500)

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=9200)
