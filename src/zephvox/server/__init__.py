"""zephvox as a service: `zephvox server serve` runs the engine for many accounts.

Accounts are created by the admin (`zephvox server accounts add`), who sends each person an
invite; every device that redeems it gets its own key. Long recordings are async jobs; practice
attempts stream over a WebSocket and run on their own threads so they stay fast.
"""
