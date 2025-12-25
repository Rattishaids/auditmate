from flask import Flask, jsonify, request, render_template
from flask_cors import CORS
from sklearn.ensemble import IsolationForest
import pandas as pd
from datetime import datetime
import requests
import json
import os
from dotenv import load_dotenv

# ------------------------
# Setup
# ------------------------
load_dotenv()

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_PATH = os.path.join(BASE_DIR, 'Auditmate Transactions - Sheet1.csv')
FEEDBACK_FILE = os.path.join(BASE_DIR, 'feedback_log.json')
N8N_WEBHOOK_URL = os.getenv('N8N_WEBHOOK_URL')

df = pd.DataFrame()
model = None
FEATURES = []
model_timestamp = None

# IMPORTANT: templates/ and static/ are auto-detected by Flask
app = Flask(__name__, template_folder="templates", static_folder="static")
CORS(app)

# ------------------------
# Helper functions
# ------------------------
def load_data():
    global df, FEATURES
    df = pd.read_csv(DATA_PATH)

    if all(f'v{i}' in df.columns for i in range(1, 29)):
        FEATURES = [f'v{i}' for i in range(1, 29)] + ['Amount']
    elif all(f'V{i}' in df.columns for i in range(1, 29)):
        FEATURES = [f'V{i}' for i in range(1, 29)] + ['Amount']
    else:
        raise Exception("Required V1–V28 columns not found")

def train_model():
    global model, model_timestamp
    model = IsolationForest(
        n_estimators=100,
        contamination=0.1,
        random_state=42
    )
    model.fit(df[FEATURES])
    model_timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

def forward_to_n8n(data):
    if not N8N_WEBHOOK_URL:
        return False
    try:
        requests.post(N8N_WEBHOOK_URL, json=data, timeout=5)
        return True
    except Exception:
        return False

# ------------------------
# UI ROUTES
# ------------------------
@app.route('/')
def home():
    return jsonify({
        "service": "AUDITMATE Backend",
        "dashboard": "/dashboard",
        "endpoints": ["/health", "/predict", "/feedback", "/retrain"]
    })

@app.route('/dashboard')
def dashboard():
    return render_template("dashboard.html")

# ------------------------
# API ROUTES
# ------------------------
@app.route('/health')
def health():
    return jsonify({
        "success": True,
        "model_ready": model is not None,
        "data_loaded": not df.empty,
        "model_timestamp": model_timestamp
    })

@app.route('/predict')
def predict():
    if model is None:
        train_model()

    preds = model.predict(df[FEATURES])
    scores = model.decision_function(df[FEATURES])

    results = []
    for idx, (_, row) in enumerate(df.iterrows()):
        results.append({
            "TransactionID": row.get("TransactionID", f"TX_{idx}"),
            "Amount": float(row["Amount"]),
            "AnomalyScore": float(scores[idx]),
            "IsAnomaly": int(preds[idx] == -1)
        })

    return jsonify({
        "success": True,
        "model_timestamp": model_timestamp,
        "total": len(results),
        "anomalies": sum(r["IsAnomaly"] for r in results),
        "results": results
    })

@app.route('/retrain', methods=['POST'])
def retrain():
    load_data()
    train_model()
    return jsonify({"success": True, "message": "Model retrained"})

@app.route('/feedback', methods=['GET', 'POST'])
def feedback():
    if request.method == 'GET':
        if not os.path.exists(FEEDBACK_FILE):
            return jsonify({"success": True, "feedbacks": []})

        with open(FEEDBACK_FILE, 'r') as f:
            feedbacks = [json.loads(line) for line in f if line.strip()]

        return jsonify({"success": True, "feedbacks": feedbacks})

    data = request.get_json()
    data["timestamp"] = data.get("timestamp", datetime.now().isoformat())

    with open(FEEDBACK_FILE, "a") as f:
        f.write(json.dumps(data) + "\n")

    forwarded = forward_to_n8n(data)

    return jsonify({
        "success": True,
        "forwarded_to_n8n": forwarded
    })

# ------------------------
# Startup
# ------------------------
if __name__ == "__main__":
    load_data()
    train_model()
    print("🚀 Backend running at http://127.0.0.1:5000")
    print("📊 Dashboard available at http://127.0.0.1:5000/dashboard")
    app.run(host="0.0.0.0", port=5000, debug=False)
