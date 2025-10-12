import os
import tempfile
import uuid
from fastapi import FastAPI, WebSocket, UploadFile, File, Form
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse, JSONResponse, FileResponse
from processing import (
    process_frame,
    process_video_file,
    save_analysis_plot,
    ANALYSIS_STORE,
)

app = FastAPI(title="Capstone Tracker API")

# Allow local dev frontend
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.get("/health")
async def health():
    return {"ok": True}

# --- Single image (immediate stream) ---
@app.post("/api/process")
async def process_image(file: UploadFile = File(...), color: str = Form("red"), conf: float = Form(0.35)):
    data = await file.read()
    try:
        out, _ = process_frame(data, color_choice=color, conf=float(conf))
    except Exception as e:
        return JSONResponse(status_code=400, content={"error": str(e)})
    return StreamingResponse(iter([out]), media_type="image/jpeg")

# --- Websocket live frames ---
@app.websocket("/ws")
async def ws_endpoint(ws: WebSocket):
    await ws.accept()
    selected_color = "red"
    conf = 0.35
    try:
        while True:
            msg = await ws.receive()
            if "bytes" in msg and msg["bytes"] is not None:
                frame_bytes = msg["bytes"]
                try:
                    annotated, _ = process_frame(frame_bytes, color_choice=selected_color, conf=conf)
                    await ws.send_bytes(annotated)
                except Exception as e:
                    await ws.send_text(f"ERR:{str(e)}")
            elif "text" in msg and msg["text"]:
                text = msg["text"].strip()
                if text.startswith("color="):
                    selected_color = text.split("=", 1)[1]
                    await ws.send_text(f"ACK:color={selected_color}")
                elif text.startswith("conf="):
                    try:
                        conf = float(text.split("=", 1)[1])
                        await ws.send_text(f"ACK:conf={conf}")
                    except ValueError:
                        await ws.send_text("ERR:bad conf")
                else:
                    await ws.send_text("ACK")
    except Exception:
        # client disconnected or network error
        pass

# --- Whole video: JSON response with URLs (preview + download + plot) ---
@app.post("/api/process_video2")
async def process_video2(video: UploadFile = File(...), color: str = Form("red"), conf: float = Form(0.35)):
    suffix = os.path.splitext(video.filename or "")[1] or ".mp4"
    with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as f_in:
        in_path = f_in.name
        data = await video.read()
        f_in.write(data)

    out_fd, out_path = tempfile.mkstemp(suffix="_annotated.mp4")
    os.close(out_fd)

    job_id = str(uuid.uuid4())
    try:
        analysis = process_video_file(in_path, out_path, color_choice=color, conf=float(conf))
        # Save analysis plot
        plot_fd, plot_path = tempfile.mkstemp(suffix="_analysis.png")
        os.close(plot_fd)
        save_analysis_plot(job_id, analysis, plot_path)
        ANALYSIS_STORE[job_id] = {"video": out_path, "plot": plot_path, "stats": analysis}
        return {
            "job_id": job_id,
            "video_url": f"/api/download/{job_id}",
            "plot_url": f"/api/plot/{job_id}",
            "stats": analysis,
            "filename": (os.path.splitext(video.filename or "output")[0] + "_annotated.mp4"),
        }
    except Exception as e:
        return JSONResponse(status_code=400, content={"error": str(e)})
    finally:
        try:
            os.remove(in_path)
        except Exception:
            pass

# Back-compat: direct file response (no stats)
@app.post("/api/process_video")
async def process_video(video: UploadFile = File(...), color: str = Form("red"), conf: float = Form(0.35)):
    suffix = os.path.splitext(video.filename or "")[1] or ".mp4"
    with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as f_in:
        in_path = f_in.name
        data = await video.read()
        f_in.write(data)
    out_fd, out_path = tempfile.mkstemp(suffix="_annotated.mp4")
    os.close(out_fd)
    try:
        _ = process_video_file(in_path, out_path, color_choice=color, conf=float(conf))
        filename = (os.path.splitext(video.filename or "output")[0] + "_annotated.mp4")
        return FileResponse(out_path, media_type="video/mp4", filename=filename)
    except Exception as e:
        return JSONResponse(status_code=400, content={"error": str(e)})
    finally:
        try:
            os.remove(in_path)
        except Exception:
            pass

@app.get("/api/download/{job_id}")
async def download_video(job_id: str):
    item = ANALYSIS_STORE.get(job_id)
    if not item:
        return JSONResponse(status_code=404, content={"error": "job not found"})
    return FileResponse(item["video"], media_type="video/mp4", filename=f"{job_id}_annotated.mp4")

@app.get("/api/plot/{job_id}")
async def get_plot(job_id: str):
    item = ANALYSIS_STORE.get(job_id)
    if not item:
        return JSONResponse(status_code=404, content={"error": "job not found"})
    return FileResponse(item["plot"], media_type="image/png", filename=f"{job_id}_analysis.png")
