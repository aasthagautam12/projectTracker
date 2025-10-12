const WS_URL =
  (location.protocol === "https:" ? "wss://" : "ws://") +
  (location.hostname || "localhost") +
  ":8000/ws";
let ws;
let sending = false;

const video = document.getElementById("video");
const canvas = document.getElementById("canvas");
const output = document.getElementById("output");
const outputVideo = document.getElementById("outputVideo");
const startBtn = document.getElementById("startCam");

const imageInput = document.getElementById("imageInput");
const submitImage = document.getElementById("submitImage");
const downloadImage = document.getElementById("downloadImage");

const videoFile = document.getElementById("videoFile");
const submitVideo = document.getElementById("submitVideo");
const downloadLink = document.getElementById("downloadLink");

const colorSel = document.getElementById("color");
const confRange = document.getElementById("conf");
const confVal = document.getElementById("confVal");

const statsEl = document.getElementById("stats");
const statsTitle = document.getElementById("statsTitle");
const plotImg = document.getElementById("plot");

const API = (path) => `http://localhost:8000${path}`;

function connectWS() {
  ws = new WebSocket(WS_URL);
  ws.binaryType = "arraybuffer";
  ws.onopen = () => {
    ws.send(`color=${colorSel.value}`);
    ws.send(`conf=${confRange.value}`);
  };
  ws.onmessage = (ev) => {
    if (typeof ev.data === "string") {
      if (ev.data.startsWith("ERR:")) console.error(ev.data);
      return;
    }
    const blob = new Blob([ev.data], { type: "image/jpeg" });
    const url = URL.createObjectURL(blob);
    output.src = url;
    output.classList.remove("hidden");
  };
  ws.onclose = () => setTimeout(connectWS, 1000);
}

async function startCamera() {
  const stream = await navigator.mediaDevices.getUserMedia({
    video: { width: 640, height: 480 },
    audio: false,
  });
  video.srcObject = stream;
  video.play();
  requestAnimationFrame(captureLoop);
}

async function captureLoop() {
  if (
    !sending &&
    ws &&
    ws.readyState === WebSocket.OPEN &&
    video.readyState >= 2
  ) {
    sending = true;
    const w = 640,
      h = 480;
    canvas.width = w;
    canvas.height = h;
    const ctx = canvas.getContext("2d");
    ctx.drawImage(video, 0, 0, w, h);
    canvas.toBlob(
      async (blob) => {
        if (blob && ws && ws.readyState === WebSocket.OPEN) {
          const buf = await blob.arrayBuffer();
          ws.send(buf);
        }
        sending = false;
      },
      "image/jpeg",
      0.7
    );
  }
  requestAnimationFrame(captureLoop);
}

startBtn.addEventListener("click", async () => {
  if (!ws || ws.readyState !== WebSocket.OPEN) connectWS();
  startCamera();
});

// Submit Image — preview + download
submitImage.addEventListener("click", async () => {
  const file = imageInput.files?.[0];
  if (!file) {
    alert("Choose an image first.");
    return;
  }
  submitImage.disabled = true;
  submitImage.textContent = "Processing…";
  try {
    const form = new FormData();
    form.append("file", file);
    form.append("color", colorSel.value);
    form.append("conf", confRange.value);
    const res = await fetch(API("/api/process"), {
      method: "POST",
      body: form,
    });
    if (!res.ok) throw new Error("Server error");
    const blob = await res.blob();
    const url = URL.createObjectURL(blob);
    output.src = url;
    output.classList.remove("hidden");
    outputVideo.classList.add("hidden");
    downloadImage.href = url;
    const base = file.name.replace(/\.[^.]+$/, "");
    downloadImage.download = base + "_annotated.jpg";
    downloadImage.style.display = "inline-block";
  } catch (err) {
    alert("Failed: " + err.message);
  } finally {
    submitImage.disabled = false;
    submitImage.textContent = "Submit Image";
  }
});

// Submit Video — JSON API returning job_id + URLs; preview in <video>
submitVideo.addEventListener("click", async () => {
  const file = videoFile.files?.[0];
  if (!file) {
    alert("Choose a video first.");
    return;
  }
  submitVideo.disabled = true;
  submitVideo.textContent = "Processing…";
  downloadLink.style.display = "none";
  statsEl.classList.add("hidden");
  statsTitle.classList.add("hidden");
  plotImg.classList.add("hidden");
  try {
    const form = new FormData();
    form.append("video", file);
    form.append("color", colorSel.value);
    form.append("conf", confRange.value);
    const res = await fetch(API("/api/process_video2"), {
      method: "POST",
      body: form,
    });
    if (!res.ok) throw new Error("Server error");
    const data = await res.json();

    // preview processed video
    const videoURL = API(data.video_url);
    outputVideo.src = videoURL;
    outputVideo.classList.remove("hidden");
    output.classList.add("hidden");

    // download link
    downloadLink.href = videoURL;
    downloadLink.download = data.filename || "annotated.mp4";
    downloadLink.style.display = "inline-block";

    // stats + matplotlib plot
    statsEl.textContent = JSON.stringify(data.stats, null, 2);
    statsEl.classList.remove("hidden");
    statsTitle.classList.remove("hidden");
    const plotURL = API(data.plot_url);
    plotImg.src = plotURL;
    plotImg.classList.remove("hidden");
  } catch (err) {
    alert("Failed to process video: " + err.message);
  } finally {
    submitVideo.disabled = false;
    submitVideo.textContent = "Submit Video";
  }
});

colorSel.addEventListener("change", () => {
  if (ws && ws.readyState === WebSocket.OPEN)
    ws.send(`color=${colorSel.value}`);
});

confRange.addEventListener("input", () => {
  confVal.textContent = confRange.value;
  if (ws && ws.readyState === WebSocket.OPEN)
    ws.send(`conf=${confRange.value}`);
});

// Logout
const logoutBtn = document.getElementById("logoutBtn");
if (logoutBtn) {
  logoutBtn.addEventListener("click", () => {
    localStorage.removeItem("auth_user");
    location.href = "login.html";
  });
}
