"""
SSSTiik Backend - TikTok Video Downloader API
"""

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
import httpx
import re
import json
from typing import Optional
import asyncio

app = FastAPI(
    title="SSSTiik API",
    description="API para download de vídeos do TikTok",
    version="1.0.0"
)

# CORS - Permitir requisições do frontend
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Em produção, especifique seu domínio: ["https://ssstiik.com"]
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Models
class DownloadRequest(BaseModel):
    url: str

class DownloadResponse(BaseModel):
    success: bool
    video: Optional[str] = None
    video_hd: Optional[str] = None
    video_sd: Optional[str] = None
    audio: Optional[str] = None
    thumbnail: Optional[str] = None
    title: Optional[str] = None
    author: Optional[str] = None
    duration: Optional[str] = None
    error: Optional[str] = None


def extract_video_id(url: str) -> Optional[str]:
    """Extrai o ID do vídeo de uma URL do TikTok"""
    patterns = [
        r'tiktok\.com\/@[\w.-]+\/video\/(\d+)',
        r'tiktok\.com\/t\/(\w+)',
        r'vm\.tiktok\.com\/(\w+)',
        r'tiktok\.com\/.*[?&]v=(\d+)',
    ]
    
    for pattern in patterns:
        match = re.search(pattern, url)
        if match:
            return match.group(1)
    return None


async def get_redirect_url(short_url: str) -> str:
    """Resolve URLs curtas do TikTok (vm.tiktok.com)"""
    async with httpx.AsyncClient(follow_redirects=True) as client:
        try:
            response = await client.head(short_url, timeout=10.0)
            return str(response.url)
        except:
            return short_url


async def fetch_tiktok_data(url: str) -> dict:
    """
    Busca dados do vídeo do TikTok usando a API interna
    
    Método: Fazer requisição para a página do TikTok e extrair dados do JSON embedded
    """
    
    # Se for URL curta, resolver primeiro
    if 'vm.tiktok.com' in url or '/t/' in url:
        url = await get_redirect_url(url)
    
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
        'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
        'Accept-Language': 'en-US,en;q=0.5',
        'Accept-Encoding': 'gzip, deflate, br',
        'Connection': 'keep-alive',
        'Upgrade-Insecure-Requests': '1',
    }
    
    async with httpx.AsyncClient() as client:
        try:
            response = await client.get(url, headers=headers, timeout=15.0, follow_redirects=True)
            html = response.text
            
            # Método 1: Extrair do SIGI_STATE
            sigi_match = re.search(r'<script id="SIGI_STATE"[^>]*>([^<]+)</script>', html)
            if sigi_match:
                try:
                    data = json.loads(sigi_match.group(1))
                    return parse_sigi_data(data)
                except json.JSONDecodeError:
                    pass
            
            # Método 2: Extrair do __UNIVERSAL_DATA_FOR_REHYDRATION__
            universal_match = re.search(r'<script id="__UNIVERSAL_DATA_FOR_REHYDRATION__"[^>]*>([^<]+)</script>', html)
            if universal_match:
                try:
                    data = json.loads(universal_match.group(1))
                    return parse_universal_data(data)
                except json.JSONDecodeError:
                    pass
            
            # Método 3: Procurar por qualquer JSON com videoData
            video_match = re.search(r'"downloadAddr"\s*:\s*"([^"]+)"', html)
            if video_match:
                video_url = video_match.group(1).encode().decode('unicode_escape')
                return {
                    'success': True,
                    'video': video_url,
                    'video_hd': video_url,
                }
            
            return {'success': False, 'error': 'Não foi possível extrair dados do vídeo'}
            
        except httpx.TimeoutException:
            return {'success': False, 'error': 'Timeout ao acessar o TikTok'}
        except Exception as e:
            return {'success': False, 'error': f'Erro ao processar: {str(e)}'}


def parse_sigi_data(data: dict) -> dict:
    """Parse dados do formato SIGI_STATE"""
    try:
        item_module = data.get('ItemModule', {})
        if item_module:
            video_id = list(item_module.keys())[0]
            video_data = item_module[video_id]
            
            video_info = video_data.get('video', {})
            author_info = video_data.get('author', {})
            
            return {
                'success': True,
                'video': video_info.get('downloadAddr') or video_info.get('playAddr'),
                'video_hd': video_info.get('downloadAddr'),
                'video_sd': video_info.get('playAddr'),
                'thumbnail': video_info.get('cover') or video_info.get('originCover'),
                'title': video_data.get('desc', 'Vídeo do TikTok'),
                'author': author_info.get('uniqueId') or author_info.get('nickname'),
                'duration': str(video_info.get('duration', '')) + 's' if video_info.get('duration') else None,
            }
    except Exception:
        pass
    
    return {'success': False, 'error': 'Formato de dados não reconhecido'}


def parse_universal_data(data: dict) -> dict:
    """Parse dados do formato __UNIVERSAL_DATA_FOR_REHYDRATION__"""
    try:
        default_scope = data.get('__DEFAULT_SCOPE__', {})
        webapp_detail = default_scope.get('webapp.video-detail', {})
        item_info = webapp_detail.get('itemInfo', {}).get('itemStruct', {})
        
        if item_info:
            video_info = item_info.get('video', {})
            author_info = item_info.get('author', {})
            
            # Pegar URL sem marca d'água se disponível
            play_addr = video_info.get('playAddr')
            download_addr = video_info.get('downloadAddr')
            
            # Tentar obter URL de bitrate list
            bitrate_list = video_info.get('bitrateInfo', [])
            if bitrate_list:
                for bitrate in bitrate_list:
                    if bitrate.get('PlayAddr', {}).get('UrlList'):
                        play_addr = bitrate['PlayAddr']['UrlList'][0]
                        break
            
            return {
                'success': True,
                'video': download_addr or play_addr,
                'video_hd': download_addr,
                'video_sd': play_addr,
                'thumbnail': video_info.get('cover') or video_info.get('originCover'),
                'title': item_info.get('desc', 'Vídeo do TikTok'),
                'author': author_info.get('uniqueId') or author_info.get('nickname'),
                'duration': str(video_info.get('duration', '')) + 's' if video_info.get('duration') else None,
            }
    except Exception:
        pass
    
    return {'success': False, 'error': 'Formato de dados não reconhecido'}


# ========== ROTAS ==========

@app.get("/")
async def root():
    """Health check"""
    return {
        "status": "online",
        "service": "SSSTiik API",
        "version": "1.0.0"
    }


@app.get("/health")
async def health_check():
    """Verificação de saúde do serviço"""
    return {"status": "healthy"}


@app.post("/api/download", response_model=DownloadResponse)
async def download_video(request: DownloadRequest):
    """
    Endpoint principal para download de vídeos do TikTok
    
    - **url**: URL do vídeo do TikTok
    """
    url = request.url.strip()
    
    # Validar URL
    if not url:
        return DownloadResponse(success=False, error="URL não fornecida")
    
    if 'tiktok.com' not in url.lower():
        return DownloadResponse(success=False, error="URL inválida. Forneça um link do TikTok.")
    
    # Buscar dados do vídeo
    result = await fetch_tiktok_data(url)
    
    if result.get('success'):
        return DownloadResponse(
            success=True,
            video=result.get('video'),
            video_hd=result.get('video_hd'),
            video_sd=result.get('video_sd'),
            audio=result.get('audio'),
            thumbnail=result.get('thumbnail'),
            title=result.get('title'),
            author=result.get('author'),
            duration=result.get('duration'),
        )
    else:
        return DownloadResponse(
            success=False,
            error=result.get('error', 'Erro desconhecido ao processar o vídeo')
        )


@app.get("/api/info")
async def get_video_info(url: str):
    """
    Obter informações do vídeo sem download
    
    - **url**: URL do vídeo do TikTok
    """
    if 'tiktok.com' not in url.lower():
        raise HTTPException(status_code=400, detail="URL inválida")
    
    result = await fetch_tiktok_data(url)
    return result


# ========== Para rodar localmente ==========
if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
