from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
import httpx
import re

app = FastAPI(title="SSSTiik API")

# CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

class VideoRequest(BaseModel):
    url: str

class VideoResponse(BaseModel):
    success: bool
    video_hd: str = None
    video_sd: str = None
    thumbnail: str = None
    title: str = None
    author: str = None
    error: str = None

@app.get("/")
async def root():
    return {"status": "ok", "service": "SSSTiik API"}

@app.get("/health")
async def health():
    return {"status": "healthy"}

async def get_tiktok_data(url: str) -> dict:
    """Extrai dados do video usando tikwm.com API"""
    
    # Limpar URL
    if "vm.tiktok.com" in url or "vt.tiktok.com" in url:
        async with httpx.AsyncClient(follow_redirects=True) as client:
            response = await client.get(url)
            url = str(response.url)
    
    # Extrair video ID
    patterns = [
        r'video/(\d+)',
        r'photo/(\d+)',
        r'/v/(\d+)',
    ]
    
    video_id = None
    for pattern in patterns:
        match = re.search(pattern, url)
        if match:
            video_id = match.group(1)
            break
    
    if not video_id:
        if '@' in url and '/' in url:
            parts = url.split('/')
            for part in parts:
                if part.isdigit() and len(part) > 10:
                    video_id = part
                    break
    
    if not video_id:
        raise HTTPException(status_code=400, detail="Nao foi possivel extrair o ID do video")
    
    api_url = f"https://www.tikwm.com/api/?url={url}"
    
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Accept": "application/json, text/javascript, */*; q=0.01",
        "Accept-Language": "en-US,en;q=0.9",
        "Referer": "https://www.tikwm.com/",
    }
    
    async with httpx.AsyncClient(timeout=30.0) as client:
        response = await client.get(api_url, headers=headers)
        
        if response.status_code != 200:
            raise HTTPException(status_code=500, detail="Erro ao conectar com servidor")
        
        data = response.json()
        
        if data.get("code") != 0:
            raise HTTPException(status_code=400, detail="Video nao encontrado ou privado")
        
        video_data = data.get("data", {})
        
        return {
            "video_hd": video_data.get('hdplay') or video_data.get('play', ''),
            "video_sd": video_data.get('play', ''),
            "thumbnail": video_data.get("cover", ""),
            "title": video_data.get("title", "Video do TikTok"),
            "author": video_data.get("author", {}).get("nickname", ""),
            "duration": video_data.get("duration", 0),
            "video_id": video_id,
        }

@app.post("/api/download", response_model=VideoResponse)
async def download_video(request: VideoRequest):
    try:
        url = request.url.strip()
        
        if not url:
            return VideoResponse(success=False, error="URL nao fornecida")
        
        if "tiktok.com" not in url:
            return VideoResponse(success=False, error="URL invalida. Use um link do TikTok.")
        
        data = await get_tiktok_data(url)
        
        return VideoResponse(
            success=True,
            video_hd=data.get("video_hd"),
            video_sd=data.get("video_sd"),
            thumbnail=data.get("thumbnail"),
            title=data.get("title"),
            author=data.get("author"),
        )
        
    except HTTPException as e:
        return VideoResponse(success=False, error=e.detail)
    except Exception as e:
        return VideoResponse(success=False, error="Erro ao processar video. Tente novamente.")

@app.get("/download")
async def download_file(url: str, filename: str = "tiktok_video"):
    """Proxy que baixa o video e entrega com nome .mp4"""
    if not url:
        raise HTTPException(status_code=400, detail="URL nao fornecida")
    
    # Limpar filename
    safe_filename = re.sub(r'[^\w\-]', '_', filename)[:50]
    if not safe_filename:
        safe_filename = "tiktok_video"
    
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Referer": "https://www.tikwm.com/",
    }
    
    async def stream_video():
        async with httpx.AsyncClient(timeout=120.0, follow_redirects=True) as client:
            async with client.stream("GET", url, headers=headers) as response:
                async for chunk in response.aiter_bytes(chunk_size=65536):
                    yield chunk
    
    return StreamingResponse(
        stream_video(),
        media_type="video/mp4",
        headers={
            "Content-Disposition": f'attachment; filename="{safe_filename}.mp4"',
            "Content-Type": "video/mp4",
        }
    )

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
