from abc import ABC, abstractmethod


class LlmClient(ABC):

    @abstractmethod
    def generate(self, prompt: str) -> str:
        pass
    