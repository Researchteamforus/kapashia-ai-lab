import os
import time
import json
import uuid
import shutil
from typing import Dict, List, Optional
from fastapi import FastAPI, Request, File, UploadFile, HTTPException
from fastapi.responses import HTMLResponse, FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

# Initialize FastAPI App
app = FastAPI(title="Kapashia AI LAB - Coordinator")

# Directories for files and artifacts
UPLOAD_DIR = "uploads"
ARTIFACT_DIR = "artifacts"
os.makedirs(UPLOAD_DIR, exist_ok=True)
os.makedirs(ARTIFACT_DIR, exist_ok=True)

# Global Node Database & Logging
nodes_data: Dict[str, dict] = {}
logs_list: List[dict] = []  # Format: { "time": "...", "event": "...", "details": "..." }

# Distributed Execution Session State
execution_state = {
    "current_task_id": None,
    "code_to_run": "",
    "status": "idle",       # "idle", "running", "completed"
    "node_targets": [],
    "progress": 0.0,
    "responses": {},        # { node_id: { output, error, completed_at } }
}

def add_log(event: str, details: str = "System Coordinator Action"):
    """Log a timestamped event with details."""
    timestamp = time.strftime("%d/%m/%Y, %H:%M:%S")
    logs_list.append({
        "time": timestamp,
        "event": event,
        "details": details
    })
    if len(logs_list) > 100:
        logs_list.pop(0)

# ==========================================
# CLIENT NODE API ENDPOINTS
# ==========================================

class RegisterPayload(BaseModel):
    node_id: str
    total_ram: float
    total_threads: int
    gpu_name: str
    gpu_vram: float

@app.post("/register")
async def register_node(payload: RegisterPayload, request: Request):
    """Endpoint for worker nodes to register hardware specifications."""
    nodes_data[payload.node_id] = {
        "node_id": payload.node_id,
        "status": "online",
        "last_ping": time.time(),
        "total_ram": payload.total_ram,
        "total_threads": payload.total_threads,
        "gpu_name": payload.gpu_name,
        "gpu_vram": payload.gpu_vram,
        "cpu_load": 0.0,
        "ram_load": 0.0,
        "tasks_completed": nodes_data.get(payload.node_id, {}).get("tasks_completed", 0),
        "connected_at": nodes_data.get(payload.node_id, {}).get("connected_at", time.time()),
        "ip": request.client.host
    }
    add_log(
        event=f"Node Registered: '{payload.node_id}'", 
        details=f"Connected from {request.client.host}. Hardware: GPU={payload.gpu_name} ({payload.gpu_vram:.1f}GB), RAM={payload.total_ram:.1f}GB."
    )
    return {"status": "registered"}

class PingPayload(BaseModel):
    node_id: str
    cpu_load: float
    ram_load: float
    total_ram: float
    total_threads: int
    gpu_name: str
    gpu_vram: float

@app.post("/ping")
async def ping_node(payload: PingPayload, request: Request):
    """Heartbeat endpoint for nodes. Dispatches python execution jobs if available."""
    now = time.time()
    
    # Update node stats
    if payload.node_id in nodes_data:
        nodes_data[payload.node_id].update({
            "status": "online",
            "last_ping": now,
            "cpu_load": payload.cpu_load,
            "ram_load": payload.ram_load
        })
    else:
        nodes_data[payload.node_id] = {
            "node_id": payload.node_id,
            "status": "online",
            "last_ping": now,
            "total_ram": payload.total_ram,
            "total_threads": payload.total_threads,
            "gpu_name": payload.gpu_name,
            "gpu_vram": payload.gpu_vram,
            "cpu_load": payload.cpu_load,
            "ram_load": payload.ram_load,
            "tasks_completed": 0,
            "connected_at": now,
            "ip": request.client.host
        }

    # Dispatch python code if this node is targeted and hasn't executed it yet
    dispatch_task = None
    if (execution_state["status"] == "running" and 
        payload.node_id not in execution_state["responses"]):
        
        if (not execution_state["node_targets"] or 
            payload.node_id in execution_state["node_targets"]):
            dispatch_task = {
                "task_id": execution_state["current_task_id"],
                "code": execution_state["code_to_run"]
            }

    return {"status": "acknowledged", "task": dispatch_task}

class ResultPayload(BaseModel):
    node_id: str
    task_id: str
    output: str
    error: Optional[str] = None

@app.post("/upload_result")
async def upload_result(payload: ResultPayload):
    """Endpoint for nodes to upload execution output."""
    if payload.task_id != execution_state["current_task_id"]:
        return {"status": "ignored"}
        
    execution_state["responses"][payload.node_id] = {
        "output": payload.output,
        "error": payload.error,
        "completed_at": time.strftime("%H:%M:%S")
    }
    
    # Increment completed tasks counter
    if payload.node_id in nodes_data:
        nodes_data[payload.node_id]["tasks_completed"] += 1
        
    add_log(
        event=f"Execution completed on '{payload.node_id}'", 
        details=f"Task ID: {payload.task_id}. Execution finished successfully." if not payload.error else f"Task ID: {payload.task_id} failed: {payload.error}"
    )
    
    # Check if all targeted nodes have completed
    with_responses = list(execution_state["responses"].keys())
    with_online = [nid for nid, nd in nodes_data.items() if nd["status"] == "online"]
    
    targets = execution_state["node_targets"] if execution_state["node_targets"] else with_online
    if all(t in with_responses for t in targets):
        execution_state["status"] = "completed"
        execution_state["progress"] = 100.0
        add_log(event="Distributed Task Completed", details=f"Task ID: {payload.task_id} executed successfully across all active targets.")
    else:
        # Calculate intermediate progress percentage
        if targets:
            execution_state["progress"] = (len(with_responses) / len(targets)) * 100.0
        
    return {"status": "received"}

# ==========================================
# FILE DOWNLOAD/UPLOAD ENDPOINTS
# ==========================================

@app.get("/download_dataset/{filename}")
async def download_dataset(filename: str):
    """Allow nodes to download dataset files from server."""
    file_path = os.path.join(UPLOAD_DIR, filename)
    if os.path.exists(file_path):
        return FileResponse(file_path)
    raise HTTPException(status_code=404, detail="Dataset not found")

@app.post("/upload_artifact")
async def upload_artifact(node_id: str, file: UploadFile = File(...)):
    """Allow nodes to upload training output files (artifacts)."""
    file_path = os.path.join(ARTIFACT_DIR, file.filename)
    with open(file_path, "wb") as buffer:
        shutil.copyfileobj(file.file, buffer)
        
    if node_id in nodes_data:
        nodes_data[node_id]["tasks_completed"] += 1
        
    add_log(
        event=f"Artifact Uploaded: '{file.filename}'", 
        details=f"Uploaded by '{node_id}' and saved to artifacts storage."
    )
    return {"status": "saved"}

# ==========================================
# WEB UI & AJAX DASHBOARD ENDPOINTS
# ==========================================

@app.get("/get_state")
async def get_state():
    """Retrieve UI metrics and node list for browser update."""
    now = time.time()
    active_nodes = []
    
    # Offline checking
    for node_id, nd in list(nodes_data.items()):
        if nd["status"] == "online" and now - nd["last_ping"] > 8.0:
            nd["status"] = "offline"
            add_log(event=f"Node went Offline: '{node_id}'", details="Heartbeat timeout: Node disconnected from coordinator.")
        active_nodes.append(nd)
        
    datasets = os.listdir(UPLOAD_DIR)
    artifacts = os.listdir(ARTIFACT_DIR)
    
    return {
        "nodes": active_nodes,
        "logs": logs_list[::-1][:5],  # Return last 5 logs reversed
        "execution": execution_state,
        "datasets": datasets,
        "artifacts": artifacts
    }

@app.get("/get_task_result/{task_id}")
async def get_task_result(task_id: str):
    """Retrieve execution result for a specific task ID (used by Python SDK)."""
    if execution_state["current_task_id"] != task_id:
        return {"status": "overwritten", "responses": {}}
    return {
        "status": execution_state["status"],
        "responses": execution_state["responses"]
    }

@app.post("/run_code")
async def run_code(request: Request):
    """Trigger a new code execution task from the Python SDK or Jupyter."""
    payload = await request.json()
    code = payload.get("code", "")
    targets = payload.get("targets", [])
    
    if not code.strip():
        raise HTTPException(status_code=400, detail="Code cannot be empty")
        
    task_id = str(uuid.uuid4())
    execution_state.update({
        "current_task_id": task_id,
        "code_to_run": code,
        "status": "running",
        "progress": 0.0,
        "node_targets": targets,
        "responses": {}
    })
    
    target_desc = f"{len(targets)} nodes" if targets else "all online nodes"
    add_log(event="Dispatched ML Task", details=f"Task ID: {task_id} sent to {target_desc} for execution.")
    return {"status": "dispatched", "task_id": task_id}

@app.post("/upload_dataset")
async def upload_dataset(file: UploadFile = File(...)):
    """Allow user to upload dataset files from browser UI."""
    file_path = os.path.join(UPLOAD_DIR, file.filename)
    with open(file_path, "wb") as buffer:
        shutil.copyfileobj(file.file, buffer)
    add_log(event=f"Dataset uploaded: '{file.filename}'", details="File uploaded via Python SDK Client.")
    return {"status": "uploaded"}

@app.get("/download_artifact/{filename}")
async def download_artifact(filename: str):
    """Allow user to download model weights/output files."""
    file_path = os.path.join(ARTIFACT_DIR, filename)
    if os.path.exists(file_path):
        return FileResponse(file_path)
    raise HTTPException(status_code=404, detail="File not found")

# ==========================================
# HIGH-FIDELITY WEB INTERFACE
# ==========================================

@app.get("/", response_class=HTMLResponse)
async def serve_dashboard():
    """Exposes a highly responsive, modern, dark-mode MLOps dashboard matching the user's template."""
    return """
    <!DOCTYPE html>
    <html lang="en">
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <title>Personal Artificial Intelligence Lab - Workspace</title>
        <link href="https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700&display=swap" rel="stylesheet">
        <script src="https://cdn.jsdelivr.net/npm/chart.js"></script>
        <style>
            :root {
                --bg-primary: #f4f5f7;
                --bg-sidebar: #f8f9fa;
                --bg-card: #ffffff;
                --border-color: #e5e7eb;
                --text-primary: #1f2937;
                --text-secondary: #6b7280;
                --accent-green: #10b981;
                --accent-blue: #3b82f6;
            }
            * {
                box-sizing: border-box;
                margin: 0;
                padding: 0;
            }
            body {
                font-family: 'Inter', sans-serif;
                background-color: var(--bg-primary);
                color: var(--text-primary);
                display: flex;
                min-height: 100vh;
            }
            
            /* Sidebar Layout */
            .sidebar {
                width: 250px;
                background-color: var(--bg-sidebar);
                border-right: 1px solid var(--border-color);
                display: flex;
                flex-direction: column;
                padding: 20px;
                position: fixed;
                height: 100vh;
            }
            .sidebar-logo {
                display: flex;
                align-items: center;
                gap: 8px;
                margin-bottom: 30px;
            }
            .sidebar-logo span {
                font-size: 20px;
                font-weight: 700;
                color: #111827;
            }
            .sidebar-menu {
                list-style: none;
                display: flex;
                flex-direction: column;
                gap: 5px;
                flex-grow: 1;
            }
            .menu-item {
                display: flex;
                align-items: center;
                gap: 12px;
                padding: 10px 15px;
                font-size: 13px;
                font-weight: 500;
                color: var(--text-secondary);
                border-radius: 6px;
                cursor: pointer;
                transition: background 0.1s, color 0.1s;
            }
            .menu-item:hover {
                background-color: #f3f4f6;
                color: #111827;
            }
            .menu-item.active {
                background-color: #111827;
                color: #ffffff;
            }
            
            /* User profile in sidebar */
            .user-profile {
                display: flex;
                align-items: center;
                gap: 12px;
                border-top: 1px solid var(--border-color);
                padding-top: 15px;
            }
            .avatar {
                width: 32px;
                height: 32px;
                border-radius: 50%;
                background-color: #111827;
                color: white;
                display: flex;
                justify-content: center;
                align-items: center;
                font-weight: bold;
                font-size: 14px;
            }
            .user-details h4 {
                font-size: 13px;
                font-weight: 600;
                color: #111827;
            }
            .user-details p {
                font-size: 11px;
                color: var(--text-secondary);
            }

            /* Main Content Container */
            .main-content {
                margin-left: 0;
                flex-grow: 1;
                display: flex;
                flex-direction: column;
            }

            /* Top Sandbox Banner */
            .sandbox-banner {
                background-color: #fef3c7;
                border-bottom: 1px solid #fde68a;
                color: #92400e;
                font-size: 11px;
                font-weight: 600;
                padding: 8px 30px;
                text-align: center;
                text-transform: uppercase;
                letter-spacing: 0.5px;
            }
            .sandbox-banner span {
                font-weight: bold;
                margin-right: 5px;
            }

            .content-workspace {
                padding: 30px;
                max-width: 1200px;
                margin: 0 auto;
                width: 100%;
            }

            /* Dashboard Title and NVIDIA Logo */
            .title-section {
                display: flex;
                justify-content: space-between;
                align-items: center;
                margin-bottom: 25px;
            }
            .title-section h2 {
                font-size: 24px;
                font-weight: 700;
                color: #111827;
                margin-bottom: 4px;
            }
            .title-section p {
                font-size: 13px;
                color: var(--text-secondary);
            }
            .nvidia-logo {
                width: 100px;
                height: auto;
            }

            /* Model Training Progress Card */
            .progress-card {
                background-color: var(--bg-card);
                border: 1px solid var(--border-color);
                border-radius: 8px;
                padding: 20px 25px;
                margin-bottom: 20px;
                box-shadow: 0 1px 2px rgba(0,0,0,0.05);
            }
            .progress-header {
                display: flex;
                justify-content: space-between;
                align-items: center;
                margin-bottom: 10px;
            }
            .progress-header span {
                font-size: 10px;
                font-weight: 700;
                color: var(--text-secondary);
                text-transform: uppercase;
                letter-spacing: 0.5px;
            }
            .progress-percentage {
                font-size: 26px;
                font-weight: 800;
                color: #111827;
                margin-bottom: 15px;
            }
            .progress-bar-bg {
                background-color: #e5e7eb;
                height: 6px;
                border-radius: 3px;
                width: 100%;
                overflow: hidden;
                margin-bottom: 12px;
            }
            .progress-bar-fill {
                background-color: #111827;
                height: 100%;
                width: 0%;
                transition: width 0.5s ease-out;
            }
            .job-name {
                font-family: monospace;
                font-size: 11px;
                color: var(--text-secondary);
            }

            /* Metrics Cards Row */
            .metrics-row {
                display: grid;
                grid-template-columns: repeat(4, 1fr);
                gap: 15px;
                margin-bottom: 25px;
            }
            .metric-card {
                background-color: var(--bg-card);
                border: 1px solid var(--border-color);
                border-radius: 8px;
                padding: 15px 20px;
                box-shadow: 0 1px 2px rgba(0,0,0,0.05);
            }
            .metric-card .title {
                font-size: 10px;
                font-weight: 700;
                color: var(--text-secondary);
                text-transform: uppercase;
                margin-bottom: 6px;
            }
            .metric-card .val {
                font-size: 20px;
                font-weight: 700;
                color: #111827;
            }

            /* Bottom Grid Layout */
            .grid-bottom {
                display: grid;
                grid-template-columns: 1fr 1fr;
                gap: 20px;
                margin-bottom: 25px;
            }
            .panel {
                background-color: var(--bg-card);
                border: 1px solid var(--border-color);
                border-radius: 8px;
                padding: 20px;
                box-shadow: 0 1px 2px rgba(0,0,0,0.05);
            }
            .panel-header {
                font-size: 14px;
                font-weight: 700;
                color: #111827;
                margin-bottom: 15px;
                display: flex;
                align-items: center;
                gap: 8px;
            }
            
            /* Leaderboard design */
            .leaderboard-list {
                display: flex;
                flex-direction: column;
                gap: 10px;
            }
            .leaderboard-row {
                border: 1px solid var(--border-color);
                border-radius: 6px;
                padding: 12px 15px;
                display: flex;
                align-items: center;
                justify-content: space-between;
                font-size: 13px;
            }
            .leaderboard-row-left {
                display: flex;
                align-items: center;
                gap: 15px;
            }
            .rank {
                font-size: 12px;
                font-weight: 700;
                color: var(--text-secondary);
                width: 15px;
            }
            .user-name {
                font-weight: 600;
                color: #111827;
            }
            .user-info {
                font-size: 10px;
                color: var(--text-secondary);
                margin-top: 2px;
            }
            .tokens-count {
                font-weight: 700;
                color: #111827;
                font-size: 13px;
            }

            /* Logs design */
            .logs-list {
                display: flex;
                flex-direction: column;
                gap: 10px;
            }
            .log-card {
                border: 1px solid var(--border-color);
                border-radius: 6px;
                padding: 12px 15px;
                font-size: 12px;
            }
            .log-card-header {
                display: flex;
                justify-content: space-between;
                color: var(--text-secondary);
                font-size: 11px;
                margin-bottom: 6px;
            }
            .log-card-event {
                font-weight: 600;
                color: #111827;
                margin-bottom: 2px;
            }
            .log-card-details {
                color: var(--text-secondary);
                font-size: 11px;
            }
            .badge-timer {
                font-size: 10px;
                background-color: #f3f4f6;
                padding: 2px 6px;
                border-radius: 4px;
                font-weight: 600;
            }

            /* File Downloads Panel */
            .files-row {
                display: grid;
                grid-template-columns: 1fr 1fr;
                gap: 20px;
            }
            .file-list {
                list-style: none;
                margin-top: 5px;
            }
            .file-list li {
                padding: 8px 12px;
                background-color: #f9fafb;
                border: 1px solid var(--border-color);
                border-radius: 4px;
                margin-bottom: 5px;
                display: flex;
                justify-content: space-between;
                align-items: center;
                font-size: 12px;
            }
            .file-list a { color: var(--accent-blue); text-decoration: none; font-weight: 600; }
            .file-list a:hover { text-decoration: underline; }
        </style>
    </head>
    <body>
        <!-- 2. Main Content View -->
        <div class="main-content">
            <div class="content-workspace">
                <!-- Title Row -->
                <div class="title-section">
                    <div>
                        <h2>Personal Artificial Intelligence Lab</h2>
                    </div>
                    <!-- Nvidia Logo -->
                    <img class="nvidia-logo" src="https://upload.wikimedia.org/wikipedia/sco/2/21/Nvidia_logo.svg" alt="Nvidia Logo">
                </div>

                <!-- Metrics Grid -->
                <div class="metrics-row">
                    <div class="metric-card">
                        <div class="title">Online Nodes</div>
                        <div class="val" id="metric-nodes">0 online</div>
                    </div>
                    <div class="metric-card">
                        <div class="title">Combined GPU RAM</div>
                        <div class="val" id="metric-gpu">0.0 GB</div>
                    </div>
                    <div class="metric-card">
                        <div class="title">Total System RAM</div>
                        <div class="val" id="metric-ram">0.0 GB</div>
                    </div>
                    <div class="metric-card">
                        <div class="title">CPU Threads</div>
                        <div class="val" id="metric-threads">0</div>
                    </div>
                </div>

                <!-- Grid Columns -->
                <div class="grid-bottom">
                    <!-- Activity Monitor -->
                    <div class="panel">
                        <div class="panel-header">📈 Activity Monitor</div>
                        <div style="position: relative; width: 100%; height: 260px;">
                            <canvas id="activity-chart"></canvas>
                        </div>
                    </div>

                    <!-- Connected Nodes -->
                    <div class="panel">
                        <div class="panel-header">🔗 Connected</div>
                        <div class="logs-list" id="connected-nodes-box">
                            <!-- Dynamic connection items list -->
                        </div>
                    </div>
                </div>

                <!-- Datasets and Artifacts Files Row -->
                <div class="files-row">
                    <div class="panel">
                        <div class="panel-header">📥 Datasets (Available for Workers)</div>
                        <ul class="file-list" id="datasets-list">
                            <!-- Dynamic Datasets list -->
                        </ul>
                    </div>
                    <div class="panel">
                        <div class="panel-header">📤 Output Artifacts (Available for Download)</div>
                        <ul class="file-list" id="artifacts-list">
                            <!-- Dynamic Artifacts list -->
                        </ul>
                    </div>
                </div>

            </div>
        </div>

        <script>
            // Global Chart.js configuration
            let chartInstance = null;
            const maxDataPoints = 15;
            const chartLabels = [];
            const cpuData = [];
            const ramData = [];

            function initChart() {
                const ctx = document.getElementById('activity-chart').getContext('2d');
                chartInstance = new Chart(ctx, {
                    type: 'line',
                    data: {
                        labels: chartLabels,
                        datasets: [
                            {
                                label: 'CPU Load (%)',
                                data: cpuData,
                                borderColor: '#3b82f6',
                                backgroundColor: 'rgba(59, 130, 246, 0.05)',
                                borderWidth: 2,
                                fill: true,
                                tension: 0.3
                            },
                            {
                                label: 'System RAM Load (%)',
                                data: ramData,
                                borderColor: '#ec4899',
                                backgroundColor: 'rgba(236, 72, 153, 0.05)',
                                borderWidth: 2,
                                fill: true,
                                tension: 0.3
                            }
                        ]
                    },
                    options: {
                        responsive: true,
                        maintainAspectRatio: false,
                        scales: {
                            y: {
                                min: 0,
                                max: 100,
                                grid: { color: '#f3f4f6' }
                            },
                            x: {
                                grid: { display: false }
                            }
                        },
                        plugins: {
                            legend: {
                                display: true,
                                position: 'top',
                                labels: { boxWidth: 12, font: { family: 'Inter', size: 11 } }
                            }
                        }
                    }
                });
            }

            // Initialize chart on script load
            window.addEventListener('load', initChart);

            // Poll API every 1 second and render metrics, progress, logs
            async function fetchState() {
                try {
                    const res = await fetch("/get_state");
                    const data = await res.json();
                    
                    // 1. Update Metrics Cards
                    const onlineNodes = data.nodes.filter(n => n.status === "online");
                    document.getElementById("metric-nodes").innerText = `${onlineNodes.length} online`;
                    
                    if (onlineNodes.length > 0) {
                        const totalGpu = onlineNodes.reduce((sum, n) => sum + n.gpu_vram, 0);
                        const totalRam = onlineNodes.reduce((sum, n) => sum + n.total_ram, 0);
                        const totalThreads = onlineNodes.reduce((sum, n) => sum + n.total_threads, 0);
                        document.getElementById("metric-gpu").innerText = `${totalGpu.toFixed(1)} GB`;
                        document.getElementById("metric-ram").innerText = `${totalRam.toFixed(1)} GB`;
                        document.getElementById("metric-threads").innerText = totalThreads;
                    } else {
                        document.getElementById("metric-gpu").innerText = "0.0 GB";
                        document.getElementById("metric-ram").innerText = "0.0 GB";
                        document.getElementById("metric-threads").innerText = "0";
                    }

                    // 2. Update Progress Bar (Removed)

                    // 3. Update Activity Monitor Chart
                    let avgCpu = 0;
                    let avgRam = 0;
                    if (onlineNodes.length > 0) {
                        avgCpu = onlineNodes.reduce((sum, n) => sum + n.cpu_load, 0) / onlineNodes.length;
                        avgRam = onlineNodes.reduce((sum, n) => sum + n.ram_load, 0) / onlineNodes.length;
                    }
                    
                    const timeLabel = new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', second: '2-digit' });
                    chartLabels.push(timeLabel);
                    cpuData.push(avgCpu);
                    ramData.push(avgRam);

                    if (chartLabels.length > maxDataPoints) {
                        chartLabels.shift();
                        cpuData.shift();
                        ramData.shift();
                    }
                    if (chartInstance) {
                        chartInstance.update();
                    }

                    // 4. Update Connected Nodes list
                    const connectedBox = document.getElementById("connected-nodes-box");
                    connectedBox.innerHTML = "";
                    if (onlineNodes.length === 0) {
                        connectedBox.innerHTML = '<div style="font-size:12px; color:var(--text-secondary); text-align:center; padding:20px;">No nodes currently connected.</div>';
                    } else {
                        onlineNodes.forEach(node => {
                            const connectedAt = node.connected_at || (Date.now() / 1000);
                            const diffSeconds = Math.floor(Date.now() / 1000 - connectedAt);
                            const hours = Math.floor(diffSeconds / 3600);
                            const minutes = Math.floor((diffSeconds % 3600) / 60);
                            const timeAgo = `${hours} Hour ${minutes} minutes Ago`;
                            
                            connectedBox.innerHTML += `
                                <div class="log-card">
                                    <div class="log-card-event" style="font-size: 13px; font-weight: 600; color: #111827;">
                                        ${node.node_id}: <span style="font-weight: normal; color: var(--text-secondary);">Connected on ${timeAgo}</span>
                                    </div>
                                </div>
                            `;
                        });
                    }

                    // 5. Update Datasets and Artifacts list
                    const dsList = document.getElementById("datasets-list");
                    dsList.innerHTML = "";
                    if (data.datasets.length === 0) {
                        dsList.innerHTML = '<li><span style="color:var(--text-secondary)">No datasets uploaded.</span></li>';
                    } else {
                        data.datasets.forEach(file => {
                            dsList.innerHTML += `<li><span>📄 ${file}</span></li>`;
                        });
                    }
                    
                    const artList = document.getElementById("artifacts-list");
                    artList.innerHTML = "";
                    if (data.artifacts.length === 0) {
                        artList.innerHTML = '<li><span style="color:var(--text-secondary)">No outputs available.</span></li>';
                    } else {
                        data.artifacts.forEach(file => {
                            artList.innerHTML += `<li><span>📦 ${file}</span> <a href="/download_artifact/${file}" target="_blank">Download</a></li>`;
                        });
                    }
                    
                } catch (e) {
                    console.log("Error fetching state:", e);
                }
            }

            setInterval(fetchState, 1000);
            fetchState();
        </script>
    </body>
    </html>
    """

if __name__ == "__main__":
    import uvicorn
    add_log("Starting local Decentralized AI LAB Coordinator on http://127.0.0.1:8080")
    uvicorn.run(app, host="0.0.0.0", port=8080)
