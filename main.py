import os
import psutil
import platform
import collections
from flask import Flask, render_template_string, jsonify

# --- ROBUST IMPORT ---
try:
    import pynvml
    HAS_NVIDIA_LIB = True
except ImportError:
    HAS_NVIDIA_LIB = False
    print("Notice: 'nvidia-ml-py' module not found. Running in CPU-only mode.")

# --- CONFIGURATION (Production Safe Defaults) ---
HOST = os.getenv("HOST", "0.0.0.0")
PORT = int(os.getenv("PORT", 9999))
UPDATE_INTERVAL = int(os.getenv("UPDATE_INTERVAL", 1000)) # 1 second
HISTORY_SIZE = 60
WARNING_THRESHOLD = 75
DANGER_THRESHOLD = 90
GPU_POWER_LIMIT = None # Auto-detect

# Colors compliant with your frontend expectations
COLORS = {
    "safe": "#76b900",
    "warning": "#ffcc00",
    "danger": "#ff3333",
    "graph_blue": "#007bff",
    "text_bright": "#ffffff"
}

app = Flask(__name__)

# --- BACKEND MONITORING ENGINE ---

class AdvancedSystemMonitor:
    def __init__(self):
        # OPTIMIZATION: Use deque for O(1) performance on rolling buffers
        self.history = {
            "gpu_util": collections.deque([0]*HISTORY_SIZE, maxlen=HISTORY_SIZE),
            "cpu_util": collections.deque([0]*HISTORY_SIZE, maxlen=HISTORY_SIZE),
            "ram_util": collections.deque([0]*HISTORY_SIZE, maxlen=HISTORY_SIZE)
        }
        self.has_gpu = False
        self.gpu_handle = None
        self.gpu_name = "N/A"
        self.driver_version = "N/A"
        self.cpu_model = "Unknown CPU"

        self._init_cpu_info()
        self._init_gpu()

    def _init_cpu_info(self):
        try:
            with open('/proc/cpuinfo', 'r') as f:
                for line in f:
                    if "model name" in line:
                        raw_name = line.split(":")[1].strip()
                        self.cpu_model = raw_name.replace("(R)", "").replace("(TM)", "").replace(" CPU", "")
                        break
        except Exception:
            self.cpu_model = platform.processor()

    def _init_gpu(self):
        if HAS_NVIDIA_LIB:
            try:
                pynvml.nvmlInit()
                self.gpu_handle = pynvml.nvmlDeviceGetHandleByIndex(0)
                self.gpu_name = pynvml.nvmlDeviceGetName(self.gpu_handle)
                if isinstance(self.gpu_name, bytes): 
                    self.gpu_name = self.gpu_name.decode('utf-8')
                self.driver_version = pynvml.nvmlSystemGetDriverVersion()
                if isinstance(self.driver_version, bytes): 
                    self.driver_version = self.driver_version.decode('utf-8')
                self.has_gpu = True
            except Exception as e:
                print(f"NVIDIA GPU initialization failed: {e}")

    def get_top_processes(self, limit=5):
        procs = []
        try:
            for p in psutil.process_iter(['pid', 'name', 'username', 'memory_percent', 'cpu_percent']):
                try:
                    # Optimization: Filter early
                    if p.info['memory_percent'] > 0.1 or p.info['cpu_percent'] > 0.1:
                        procs.append(p.info)
                except (psutil.NoSuchProcess, psutil.AccessDenied):
                    continue
        except Exception:
            pass
        # Sort in place is faster
        procs.sort(key=lambda x: x['memory_percent'], reverse=True)
        return procs[:limit]

    def get_full_stats(self):
        # Non-blocking calls
        cpu_global = psutil.cpu_percent(interval=None)
        cpu_cores = psutil.cpu_percent(interval=None, percpu=True)
        ram = psutil.virtual_memory()
        swap = psutil.swap_memory()
        disk = psutil.disk_usage('/')

        # Deque handles rotation automatically (O(1))
        self.history["cpu_util"].append(cpu_global)
        self.history["ram_util"].append(ram.percent)

        stats = {
            "os": f"{platform.system()} {platform.release()}",
            "cpu": {
                "model": self.cpu_model,
                "global_usage": cpu_global,
                "history": list(self.history["cpu_util"]), # Convert deque to list for JSON
                "cores": cpu_cores,
                "count_physical": psutil.cpu_count(logical=False),
                "count_logical": psutil.cpu_count(logical=True)
            },
            "memory": {
                "ram_percent": ram.percent,
                "ram_used_gb": round(ram.used / (1024**3), 1),
                "ram_total_gb": round(ram.total / (1024**3), 0),
                "ram_history": list(self.history["ram_util"]),
                "swap_percent": swap.percent,
                "swap_used_gb": round(swap.used / (1024**3), 1),
                "swap_total_gb": round(swap.total / (1024**3), 0)
            },
            "storage": {
                 "root_percent": disk.percent,
                 "root_used_gb": round(disk.used / (1024**3), 0),
                 "root_total_gb": round(disk.total / (1024**3), 0),
            },
            "processes": self.get_top_processes(),
            "gpu": {"available": False}
        }

        if self.has_gpu:
            try:
                util = pynvml.nvmlDeviceGetUtilizationRates(self.gpu_handle)
                mem = pynvml.nvmlDeviceGetMemoryInfo(self.gpu_handle)
                temp = pynvml.nvmlDeviceGetTemperature(self.gpu_handle, pynvml.NVML_TEMPERATURE_GPU)
                fan = pynvml.nvmlDeviceGetFanSpeed(self.gpu_handle)
                
                try:
                    power_w = pynvml.nvmlDeviceGetPowerUsage(self.gpu_handle) / 1000.0
                    if GPU_POWER_LIMIT is not None:
                        power_lim = GPU_POWER_LIMIT
                    else:
                        power_lim = pynvml.nvmlDeviceGetEnforcedPowerLimit(self.gpu_handle) / 1000.0
                except Exception:
                    power_w, power_lim = 0, 0
                
                try:
                    tx = pynvml.nvmlDeviceGetPcieThroughput(self.gpu_handle, pynvml.NVML_PCIE_UTIL_TX_BYTES) / (1024**2)
                    rx = pynvml.nvmlDeviceGetPcieThroughput(self.gpu_handle, pynvml.NVML_PCIE_UTIL_RX_BYTES) / (1024**2)
                except Exception:
                    tx, rx = 0, 0

                self.history["gpu_util"].append(util.gpu)

                stats["gpu"] = {
                    "available": True,
                    "name": self.gpu_name,
                    "driver": self.driver_version,
                    "utilization": util.gpu,
                    "history": list(self.history["gpu_util"]),
                    "vram_percent": round((mem.used / mem.total) * 100, 1),
                    "vram_used_gb": round(mem.used / (1024**3), 1),
                    "vram_total_gb": round(mem.total / (1024**3), 0),
                    "temp_c": temp,
                    "fan_percent": fan,
                    "power_w": round(power_w, 0),
                    "power_limit_w": round(power_lim, 0),
                    "pcie_tx_mb": round(tx, 0),
                    "pcie_rx_mb": round(rx, 0)
                }
            except Exception:
                 # If GPU fails mid-operation, mark unavailable but don't crash
                 self.has_gpu = False

        return stats

monitor = AdvancedSystemMonitor()

# --- FRONTEND (EXACTLY AS PROVIDED) ---
HTML_TEMPLATE = """
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>NeuroDash // AI Monitor</title>
    <style>
        :root {
            --bg-main: #0a0a0a;
            --bg-card: #141414;
            --nvidia-green: #76b900;
            --nvidia-green-dim: #76b90044;
            --graph-blue: #007bff;
            --text-bright: #ffffff;
            --text-dim: #888888;
            --danger: #ff3333;
        }
        * { box-sizing: border-box; } 
        body {
            background-color: var(--bg-main);
            color: var(--text-bright);
            font-family: 'Segoe UI', Roboto, Helvetica, Arial, sans-serif;
            margin: 0;
            padding: 20px;
            overflow-x: hidden;
        }
        
        /* HEADER */
        .header { display: flex; justify-content: space-between; align-items: center; margin-bottom: 20px; padding: 0 10px;}
        .header h1 { margin: 0; font-size: 1.5rem; text-transform: uppercase; letter-spacing: 2px;}
        .header .sub-info { font-size: 0.8rem; color: var(--text-dim); text-align: right;}

        .dashboard-grid {
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(300px, 1fr));
            gap: 25px;
            max-width: 1400px;
            margin: 0 auto;
            width: 100%;
        }

        .card {
            background-color: var(--bg-card);
            border-radius: 8px;
            padding: 25px;
            box-shadow: 0 8px 16px rgba(0,0,0,0.4);
            border: 1px solid #222;
            display: flex;
            flex-direction: column;
        }
        
        .card-header {
            display: flex; justify-content: space-between; align-items: center;
            margin-bottom: 20px; border-bottom: 1px solid #222; padding-bottom: 10px;
        }
        .card-title { font-size: 1.1rem; font-weight: 600; text-transform: uppercase; letter-spacing: 1px; color: var(--text-dim); white-space: nowrap;}
        
        /* Subtitle aligné à droite et propre */
        .card-subtitle { font-size: 0.9rem; color: var(--nvidia-green); font-weight: bold; text-align: right;}

        .split-layout { display: flex; justify-content: space-between; align-items: center; height: 100%;}
        .gauge-side { width: 40%; display: flex; flex-direction: column; align-items: center; position: relative;}
        
        .big-value-container { position: absolute; top: 55%; left: 50%; transform: translate(-50%, -50%); text-align: center;}
        .big-value { font-size: 2.5rem; font-weight: 800; line-height: 1;}
        .big-unit { font-size: 1.2rem; color: var(--nvidia-green); }
        .sub-value { font-size: 0.9rem; color: var(--text-dim); margin-top: 5px;}

        canvas.gauge { width: 180px; height: 180px; }
        canvas.graph { width: 100%; height: 100px; }
        .graph-label {font-size: 0.75rem; color: var(--text-dim); margin-bottom: 5px; text-transform: uppercase;}

        .metrics-grid { display: grid; grid-template-columns: repeat(3, 1fr); gap: 15px; margin-top: 15px;}
        .metric-box { background: #1a1a1a; padding: 10px; border-radius: 6px; text-align: center; border: 1px solid #2a2a2a;}
        .metric-box .label { font-size: 0.7rem; color: var(--text-dim); display: block; margin-bottom: 5px;}
        .metric-box .value { font-size: 1.2rem; font-weight: bold; color: var(--text-bright);}
        .metric-box .unit { font-size: 0.8rem; color: var(--nvidia-green);}

        .cpu-cores-grid {
            display: grid; grid-template-columns: repeat(auto-fill, minmax(40px, 1fr));
            gap: 4px; margin-top: 15px; height: 80px;
        }
        .core-bar-container { background-color: #111; height: 100%; width: 100%; position: relative; overflow: hidden;}
        .core-bar-fill { position: absolute; bottom: 0; left:0; width: 100%; background-color: var(--nvidia-green); transition: height 0.3s ease;}
        
        .storage-section { margin-top: 20px; display: flex; gap: 20px;}
        .mini-gauge-container { text-align: center; width: 50%; background: #1a1a1a; padding: 15px; border-radius: 8px;}

        table { width: 100%; border-collapse: collapse; font-size: 0.85rem; margin-top: 10px; }
        th { text-align: left; color: var(--text-dim); border-bottom: 1px solid #333; padding: 8px 0; font-size: 0.75rem;}
        td { padding: 6px 0; border-bottom: 1px solid #222; }
        .proc-mem { color: var(--nvidia-green); font-weight: bold; }
        .proc-name { color: #fff; }

        @media (max-width: 768px) {
            body { padding: 10px; } 
            .dashboard-grid { grid-template-columns: 1fr; }
            .card-header { flex-direction: column; align-items: flex-start; gap: 5px; }
            .card-subtitle { text-align: left; margin-top: 2px; word-break: break-word; }
            .split-layout { flex-direction: column; }
            .gauge-side { width: 100%; margin-bottom: 20px;}
            .big-value-container { position: static; transform: none; margin-top: -40px; margin-bottom: 20px;}
            .metrics-grid { grid-template-columns: repeat(2, 1fr); }
            .card { padding: 15px; }
        }
    </style>
</head>
<body>

    <div class="header">
        <h1><span style="color: var(--nvidia-green)">AI</span> WORKSTATION MONITOR</h1>
        <div class="sub-info" id="osInfo">Initializing...</div>
    </div>

    <div class="dashboard-grid">
        
        <div class="card" id="gpuCard">
            <div class="card-header">
                <span class="card-title">GPU Accelerator</span>
                <span class="card-subtitle" id="gpuName">No GPU Detected</span>
            </div>
            <div class="split-layout">
                <div class="gauge-side">
                    <canvas id="gpuUtilGauge" class="gauge" width="180" height="180"></canvas>
                    <div class="big-value-container">
                        <span class="big-value" id="gpuUtilVal">0</span><span class="big-unit">%</span>
                        <div class="sub-value">Compute Load</div>
                    </div>
                </div>
                <div class="gauge-side">
                     <canvas id="vramGauge" class="gauge" width="180" height="180"></canvas>
                     <div class="big-value-container">
                         <span class="big-value" id="vramVal">0</span><span class="big-unit">GB</span>
                         <div class="sub-value" id="vramTotal">of 0 GB</div>
                     </div>
                </div>
            </div>
            <div class="metrics-grid">
                <div class="metric-box">
                    <span class="label">TEMP</span>
                    <span class="value" id="gpuTemp">0</span><span class="unit">°C</span>
                </div>
                <div class="metric-box">
                    <span class="label">POWER</span>
                    <span class="value" id="gpuPower">0</span><span class="unit">W</span>
                </div>
                 <div class="metric-box">
                    <span class="label">FAN</span>
                    <span class="value" id="gpuFan">0</span><span class="unit">%</span>
                </div>
                 <div class="metric-box">
                    <span class="label">DRIVER</span>
                    <span class="value" style="font-size: 0.9rem;" id="gpuDriver">N/A</span>
                </div>
                <div class="metric-box">
                    <span class="label">PCIe TX</span>
                    <span class="value" id="pcieTx">0</span><span class="unit">MB/s</span>
                </div>
                <div class="metric-box">
                    <span class="label">PCIe RX</span>
                    <span class="value" id="pcieRx">0</span><span class="unit">MB/s</span>
                </div>
            </div>
             <div style="margin-top:15px;">
                 <div class="graph-label">GPU Load History (60s)</div>
                 <canvas id="gpuGraph" class="graph" width="400" height="100"></canvas>
             </div>
        </div>

        <div class="card">
             <div class="card-header">
                <span class="card-title">Processor & Memory</span>
                <span class="card-subtitle" id="cpuCountInfo">Cores</span>
            </div>
             <div class="split-layout">
                <div class="gauge-side">
                    <canvas id="cpuGauge" class="gauge" width="180" height="180"></canvas>
                    <div class="big-value-container">
                        <span class="big-value" id="cpuVal">0</span><span class="big-unit">%</span>
                        <div class="sub-value">Global Load</div>
                    </div>
                </div>
                 <div class="gauge-side">
                    <canvas id="ramGauge" class="gauge" width="180" height="180"></canvas>
                    <div class="big-value-container">
                        <span class="big-value" id="ramVal">0</span><span class="big-unit">GB</span>
                        <div class="sub-value" id="ramTotal">of 0 GB RAM</div>
                    </div>
                </div>
            </div>
             <div style="margin-top:15px;">
                 <div class="graph-label">CPU History (60s)</div>
                 <canvas id="cpuGraph" class="graph" width="400" height="80"></canvas>
             </div>
            <div style="margin-top: 20px;">
                 <div class="graph-label" style="margin-bottom: 5px;">Logical Core Load</div>
                 <div id="cpuCoresContainer" class="cpu-cores-grid"></div>
            </div>
        </div>

         <div class="card">
            <div class="card-header">
                <span class="card-title">Storage & Processes</span>
            </div>
            <div class="storage-section">
                <div class="mini-gauge-container">
                     <div class="graph-label">Main SSD (/)</div>
                     <canvas id="ssdGauge" class="gauge" width="120" height="120" style="width:120px; height:120px;"></canvas>
                     <div style="font-size:1.2rem; font-weight:bold;"><span id="ssdVal">0</span>%</div>
                     <div class="sub-value"><span id="ssdUsed">0</span> / <span id="ssdTotal">0</span> GB</div>
                </div>
                <div class="mini-gauge-container">
                     <div class="graph-label">Swap Mem</div>
                     <canvas id="swapGauge" class="gauge" width="120" height="120" style="width:120px; height:120px;"></canvas>
                     <div style="font-size:1.2rem; font-weight:bold;"><span id="swapVal">0</span>%</div>
                     <div class="sub-value"><span id="swapUsed">0</span> / <span id="swapTotal">0</span> GB</div>
                </div>
            </div>
            <div style="margin-top: 25px; border-top: 1px solid #222; padding-top: 15px;">
                <span class="card-title" style="font-size: 0.9rem;">Top Resource Consumers</span>
                <table>
                    <thead>
                        <tr>
                            <th>USER</th>
                            <th>PROCESS</th>
                            <th style="text-align:right">CPU</th>
                            <th style="text-align:right">MEM</th>
                        </tr>
                    </thead>
                    <tbody id="procTable"></tbody>
                </table>
            </div>
         </div>
    </div> 

<script>
    const NVIDIA_GREEN = "{{ COLORS.safe }}";
    const GRAPH_BLUE = "{{ COLORS.graph_blue }}";
    const BG_DIM = "#222";
    const WARNING_THRESHOLD = {{ WARNING_THRESHOLD }};
    const DANGER_THRESHOLD = {{ DANGER_THRESHOLD }};
    const COLORS = {
        warning: "{{ COLORS.warning }}",
        danger: "{{ COLORS.danger }}",
        text_bright: "{{ COLORS.text_bright }}"
    };

    function drawGauge(canvasId, percentage, color, thin=false) {
        const canvas = document.getElementById(canvasId);
        if (!canvas) return;
        const ctx = canvas.getContext('2d');
        const cx = canvas.width / 2;
        const cy = canvas.height / 2;
        const radius = thin ? canvas.width * 0.4 : canvas.width * 0.42;
        const lineWidth = thin ? 8 : 15;
        const startAngle = -Math.PI; 
        const endAngle = 0; 

        ctx.clearRect(0, 0, canvas.width, canvas.height);
        ctx.beginPath();
        ctx.arc(cx, cy, radius, startAngle, endAngle);
        ctx.lineWidth = lineWidth;
        ctx.strokeStyle = BG_DIM;
        ctx.lineCap = 'round';
        ctx.stroke();

        if (percentage > 0) {
            const currentAngle = startAngle + (percentage / 100) * (endAngle - startAngle);
            ctx.beginPath();
            ctx.arc(cx, cy, radius, startAngle, currentAngle);
            ctx.lineWidth = lineWidth;
            ctx.strokeStyle = percentage > DANGER_THRESHOLD ? COLORS.danger : percentage > WARNING_THRESHOLD ? COLORS.warning : color;
            ctx.lineCap = 'round';
            ctx.stroke();
        }
    }

    function drawGraph(canvasId, dataPoints, color) {
        const canvas = document.getElementById(canvasId);
        if (!canvas) return;
        const ctx = canvas.getContext('2d');
        const width = canvas.width;
        const height = canvas.height;
        const padding = 5;
        
        ctx.clearRect(0, 0, width, height);
        if (dataPoints.length < 2) return;

        ctx.beginPath();
        ctx.moveTo(0, height);
        const step = width / (dataPoints.length - 1);
        
        let gradient = ctx.createLinearGradient(0, 0, 0, height);
        gradient.addColorStop(0, color + "66");
        gradient.addColorStop(1, color + "00"); 

        ctx.fillStyle = gradient;
        ctx.moveTo(0, height);
        for (let i = 0; i < dataPoints.length; i++) {
            const val = dataPoints[i];
            const y = height - (val / 100 * (height - padding*2) + padding);
            ctx.lineTo(i * step, y);
        }
        ctx.lineTo(width, height);
        ctx.fill();

        ctx.beginPath();
        for (let i = 0; i < dataPoints.length; i++) {
            const val = dataPoints[i];
            const y = height - (val / 100 * (height - padding*2) + padding);
            if (i===0) ctx.moveTo(i * step, y);
            else ctx.lineTo(i * step, y);
        }
        ctx.strokeStyle = color;
        ctx.lineWidth = 2;
        ctx.stroke();
    }

    function updateCpuCores(coresData) {
        const container = document.getElementById('cpuCoresContainer');
        if (container.children.length === 0) {
            coresData.forEach((_, index) => {
                const wrapper = document.createElement('div');
                wrapper.innerHTML = `<div class="core-bar-container"><div class="core-bar-fill" id="coreBar${index}"></div></div>`;
                container.appendChild(wrapper);
            });
        }
        coresData.forEach((usage, index) => {
            const bar = document.getElementById(`coreBar${index}`);
            if (bar) {
                 bar.style.height = usage + "%";
                 bar.style.backgroundColor = usage > DANGER_THRESHOLD ? "var(--danger)" : usage > WARNING_THRESHOLD ? COLORS.warning : "var(--nvidia-green)";
            }
        });
    }

    function updateProcessTable(procs) {
        const tbody = document.getElementById('procTable');
        let html = '';
        procs.forEach(p => {
            html += `<tr><td>${p.username}</td><td class="proc-name">${p.name.substring(0, 20)}</td><td style="text-align:right">${p.cpu_percent.toFixed(0)}%</td><td style="text-align:right" class="proc-mem">${p.memory_percent.toFixed(1)}%</td></tr>`;
        });
        tbody.innerHTML = html;
    }

    let isFirstLoad = true;

    async function updateDashboard() {
        try {
            const response = await fetch('/api/full_stats');
            const data = await response.json();

            if (isFirstLoad) {
                document.getElementById('osInfo').innerText = data.os;
                document.getElementById('cpuCountInfo').innerHTML = `
                    <div style="font-size:0.8rem; color:var(--text-bright); margin-bottom:2px;">${data.cpu.model}</div>
                    ${data.cpu.count_physical} Phys / ${data.cpu.count_logical} Log
                `;
                
                if (data.gpu.available) document.getElementById('gpuName').innerText = data.gpu.name;
                isFirstLoad = false;
            }

            drawGauge('cpuGauge', data.cpu.global_usage, NVIDIA_GREEN);
            document.getElementById('cpuVal').innerText = data.cpu.global_usage.toFixed(1);
            drawGraph('cpuGraph', data.cpu.history, GRAPH_BLUE);
            updateCpuCores(data.cpu.cores);

            drawGauge('ramGauge', data.memory.ram_percent, NVIDIA_GREEN);
            document.getElementById('ramVal').innerText = data.memory.ram_used_gb;
            document.getElementById('ramTotal').innerText = `of ${data.memory.ram_total_gb} GB`;

            drawGauge('ssdGauge', data.storage.root_percent, NVIDIA_GREEN, true);
            document.getElementById('ssdVal').innerText = data.storage.root_percent;
            document.getElementById('ssdUsed').innerText = data.storage.root_used_gb;
            document.getElementById('ssdTotal').innerText = data.storage.root_total_gb;

            drawGauge('swapGauge', data.memory.swap_percent, NVIDIA_GREEN, true);
            document.getElementById('swapVal').innerText = data.memory.swap_percent.toFixed(1);
            document.getElementById('swapUsed').innerText = data.memory.swap_used_gb;
            document.getElementById('swapTotal').innerText = data.memory.swap_total_gb;

            updateProcessTable(data.processes);

            const gpuCard = document.getElementById('gpuCard');
            if (data.gpu && data.gpu.available) {
                gpuCard.style.opacity = "1";
                drawGauge('gpuUtilGauge', data.gpu.utilization, NVIDIA_GREEN);
                document.getElementById('gpuUtilVal').innerText = data.gpu.utilization;
                drawGauge('vramGauge', data.gpu.vram_percent, NVIDIA_GREEN);
                document.getElementById('vramVal').innerText = data.gpu.vram_used_gb;
                document.getElementById('vramTotal').innerText = `of ${data.gpu.vram_total_gb} GB`;
                drawGraph('gpuGraph', data.gpu.history, GRAPH_BLUE);
                document.getElementById('gpuTemp').innerText = data.gpu.temp_c;
                const powerPercentage = data.gpu.power_limit_w ? (data.gpu.power_w / data.gpu.power_limit_w) * 100 : 0;
                const powerColor = powerPercentage > DANGER_THRESHOLD ? COLORS.danger : powerPercentage > WARNING_THRESHOLD ? COLORS.warning : COLORS.text_bright;
                document.getElementById('gpuPower').innerHTML = data.gpu.power_limit_w ? `<span style="color: ${powerColor}">${data.gpu.power_w} / ${data.gpu.power_limit_w}</span>` : data.gpu.power_w;
                document.getElementById('gpuFan').innerText = data.gpu.fan_percent;
                document.getElementById('gpuDriver').innerText = data.gpu.driver;
                document.getElementById('pcieTx').innerText = data.gpu.pcie_tx_mb;
                document.getElementById('pcieRx').innerText = data.gpu.pcie_rx_mb;
            } else {
                gpuCard.style.opacity = "0.5";
                document.getElementById('gpuName').innerText = "NO NVIDIA GPU";
            }
        } catch (e) { console.error(e); }
    }
    setInterval(updateDashboard, {{ UPDATE_INTERVAL }});
    updateDashboard();
</script>
</body>
</html>
"""

@app.route('/')
def index():
    return render_template_string(
        HTML_TEMPLATE,
        UPDATE_INTERVAL=UPDATE_INTERVAL,
        WARNING_THRESHOLD=WARNING_THRESHOLD,
        DANGER_THRESHOLD=DANGER_THRESHOLD,
        COLORS=COLORS
    )

@app.route('/api/full_stats')
def full_stats():
    return jsonify(monitor.get_full_stats())

if __name__ == "__main__":
    # In PROD, this block is ignored by Gunicorn.
    # It allows easy local testing.
    print(f"Monitoring available at http://{HOST}:{PORT}")
    app.run(host=HOST, port=PORT, threaded=True)