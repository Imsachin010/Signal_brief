import asyncio
from backend.main import controller
from backend.domain import Priority, Message

async def test():
    # Make sure we have enough state initialized
    await controller.reset()
    await controller.start_scenario()
    
    # Put a dummy message into the controller
    msg = Message(
        id='test1',
        sender='Anika - Manager',
        text='When you park, send me the release readiness summary.',
        received_at='2026-04-20T11:13:00Z',
        status='deferred',
        priority='actionable'
    )
    msg.triage_action = 'HOLD_FOR_DIGEST'
    msg.triage_score = 0.637
    controller._messages.append(msg)
    
    # Set signal to 85
    print('Calling set_demo_signal with 85...')
    res = await controller.set_demo_signal(signal_strength=85, location_name='Highway')
    for m in res.get("messages", controller._messages):
        print(f'{m.sender}: status={m.status}, score={m.triage_score}, action={m.triage_action}, reason={getattr(m, "decision_reason", "")}')

asyncio.run(test())
