"""Provider-local dependency adapter contracts.

The adapters are intentionally explicit.  A provider is not considered
neutralized merely because a selector was observed; an implementation must
return execution evidence proving the real and sham boundaries.
"""
from dataclasses import dataclass


@dataclass(frozen=True)
class ProviderAdapter:
    provider: str
    address: str
    selector: str
    callback_selector: str
    boundary: str

    def validate_frame(self, calls: list[dict]) -> bool:
        """Require one exact provider frame and its callback edge."""
        provider = self.address.lower()
        frames = [c for c in calls if str(c.get("to", "")).lower() == provider
                  and str(c.get("selector", "")).lower() == self.selector]
        if len(frames) != 1:
            return False
        index = calls.index(frames[0])
        return any(str(c.get("from", "")).lower() == provider
                   and str(c.get("selector", "")).lower() == self.callback_selector
                   for c in calls[index + 1:])

    def execute(self, *_args, **_kwargs):
        """Reserved seam for a real B2 provider mutation implementation."""
        raise NotImplementedError(
            f"{self.provider} dependency neutralization adapter is not implemented")


ADAPTERS = {
    "balancer": ProviderAdapter("Balancer Vault", "0xba12222222228d8ba445958a75a0704d566bf2c8", "0x5c38449e", "0xf04f2707", "Vault -> receiver callback"),
    "morpho": ProviderAdapter("Morpho", "0xbbbbbbbbbb9cc5e90e3b3af64bdaf62c37eeffcb", "0xe0232b42", "0x31f57072", "Morpho -> loan callback"),
    "aave_v3": ProviderAdapter("Aave V3", "0xc13e21b648a5ee794902342038ff3adab66be987", "0x42b0b77c", "0x1b11d0ff", "Pool -> receiver callback"),
}


def adapter_for(provider: str) -> ProviderAdapter:
    key = provider.lower().replace(" ", "_")
    if key == "balancer_vault": key = "balancer"
    if key == "aave_v3": key = "aave_v3"
    if key not in ADAPTERS:
        raise KeyError(f"no provider adapter: {provider}")
    return ADAPTERS[key]
