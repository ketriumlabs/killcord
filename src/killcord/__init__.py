"""killcord — spending caps, rate limits, a big red pause button, and safe resume
for any agent loop.
"""

from killcord.core.action import Action
from killcord.core.rate import Rate
from killcord.core.tripwire import Tripwire, TripwireTripped, guarded

__version__ = "0.1.0"

__all__ = ["Action", "Rate", "Tripwire", "TripwireTripped", "guarded", "__version__"]
