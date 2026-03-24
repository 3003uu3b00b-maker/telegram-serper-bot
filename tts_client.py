import os
import wave
import subprocess
import asyncio
from google import genai
from google.genai import types
from config import GEMINI_API_KEY

import logging
logger = logging.getLogger(__name__)


def _save_wav(filename: str, pcm: bytes, channels=1, rate=24000, sample_width=2):
    """PCMデータをWAVファイルとして保存"""
    with wave.open(filename, "wb") as wf:
        wf.setnchannels(channels)
        wf.setsampwidth(sample_width)
        wf.setframerate(rate)
        wf.writeframes(pcm)


def _convert_wav_to_mp3(wav_path: str, mp3_path: str):
    """ffmpegでWAV→MP3変換"""
    subprocess.run(
        ["ffmpeg", "-y", "-i", wav_path, "-codec:a", "libmp3lame", "-q:a", "2", mp3_path],
        capture_output=True,
        check=True,
    )
    os.remove(wav_path)


def _sync_tts(text: str, output_path: str) -> str:
    """同期版TTS処理（スレッドで実行される）"""
    client = genai.Client(api_key=GEMINI_API_KEY)

    prompt = f"以下の内容を自然な日本語で読み上げてください:\n\n{text[:4000]}"

    logger.info(f"Gemini TTS呼び出し開始 (テキスト長: {len(text[:4000])}文字)")

    response = client.models.generate_content(
        model="gemini-2.5-flash-preview-tts",
        contents=prompt,
        config=types.GenerateContentConfig(
            response_modalities=["AUDIO"],
            speech_config=types.SpeechConfig(
                voice_config=types.VoiceConfig(
                    prebuilt_voice_config=types.PrebuiltVoiceConfig(
                        voice_name="Kore",
                    )
                )
            ),
        ),
    )

    audio_data = response.candidates[0].content.parts[0].inline_data.data
    logger.info(f"Gemini TTS応答取得: {len(audio_data)} bytes")

    wav_path = output_path.replace(".mp3", ".wav")
    _save_wav(wav_path, audio_data)
    _convert_wav_to_mp3(wav_path, output_path)

    logger.info(f"MP3生成完了: {output_path}")
    return output_path


async def text_to_mp3(text: str, output_path: str) -> str:
    """テキストをGemini TTSでMP3に変換して保存（非同期ラッパー）"""
    return await asyncio.to_thread(_sync_tts, text, output_path)
