"""
Benchmark utility for latency and VRAM measurements.
"""
import time
import subprocess
import asyncio
import shutil
from typing import Optional
from .ollama import OllamaClient
from .config import Config


class Benchmark:
    """Measures latency and performance metrics."""

    def __init__(self, config: Config):
        self.config = config
        self.results = {}

    async def run(self) -> dict:
        """Run all benchmarks."""
        self.results = {}
        
        # First token latency
        self.results["first_token"] = await self._measure_first_token()
        
        # Tokens per second
        self.results["tokens_per_second"] = await self._measure_throughput()
        
        # VRAM usage
        self.results["vram"] = self._measure_vram()
        
        return self.results

    async def _measure_first_token(self) -> float:
        """Measure time to first token."""
        client = OllamaClient(self.config.ollama_url)
        
        start = time.perf_counter()
        first_token_time = None
        
        async for chunk in client.chat(
            model=self.config.model,
            messages=[{"role": "user", "content": "Hello"}],
            num_ctx=self.config.num_ctx,
            num_predict=512,
        ):
            if first_token_time is None:
                first_token_time = time.perf_counter()
                break
        
        await client.close()
        
        if first_token_time:
            return first_token_time - start
        return -1.0

    async def _measure_throughput(self) -> float:
        """Measure tokens per second."""
        client = OllamaClient(self.config.ollama_url)
        
        start = time.perf_counter()
        token_count = 0
        
        async for chunk in client.chat(
            model=self.config.model,
            messages=[{"role": "user", "content": "Write a 100 word story about coding"}],
            num_ctx=self.config.num_ctx,
            num_predict=512,
        ):
            token_count += len(chunk)
        
        elapsed = time.perf_counter() - start
        await client.close()
        
        if elapsed > 0:
            return token_count / elapsed
        return 0.0

    def _measure_vram(self) -> Optional[dict]:
        """Measure peak VRAM usage."""
        nvidia_smi = shutil.which("nvidia-smi")
        if not nvidia_smi:
            return None
        
        try:
            result = subprocess.run(
                ["nvidia-smi", "--query-gpu=memory.total,memory.used", "--format=csv,noheader,nounits"],
                capture_output=True, text=True, timeout=5
            )
            if result.returncode == 0:
                lines = result.stdout.strip().split("\n")
                gpus = []
                for i, line in enumerate(lines):
                    total, used = map(int, line.split(","))
                    gpus.append({
                        "index": i,
                        "total_mb": total,
                        "used_mb": used,
                        "free_mb": total - used,
                    })
                return {"gpus": gpus}
        except Exception:
            pass
        return None