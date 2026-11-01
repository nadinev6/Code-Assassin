"""
Integration tests (opt-in, requires Ollama/Piper).
"""
import pytest
import os


@pytest.mark.skipif(
    not os.environ.get("CODE_ASSASSIN_INTEGRATION"),
    reason="Integration tests require CODE_ASSASSIN_INTEGRATION=1"
)
class TestIntegration:
    """Integration tests requiring Ollama and Piper."""
    
    def test_ollama_chat(self):
        """Test Ollama chat endpoint."""
        from code_assassin.ollama import OllamaClient
        import asyncio
        
        async def run():
            client = OllamaClient("http://127.0.0.1:11434")
            available = await client.check_available()
            assert available
            
            tokens = []
            async for chunk in client.chat(
                model="qwen2.5-coder:3b",
                messages=[{"role": "user", "content": "Say hello"}],
                num_ctx=2048,
                num_predict=100,
            ):
                tokens.append(chunk)
            
            assert len(tokens) > 0
            await client.close()
        
        asyncio.run(run())
    
    def test_piper_synthesis(self):
        """Test Piper voice synthesis."""
        pytest.skip("Requires voice files and audio device")


# Conditionally run integration tests
if __name__ == "__main__":
    pytest.main([__file__, "-v"])