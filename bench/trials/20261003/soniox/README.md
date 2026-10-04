# Soniox smoke trial prepared on 2026-10-03

Actual model trial: **pending local API credential**. No cloud request has been made and no audio has been sent.

The existing `10-noticias-apertura.wav` is 69.993 seconds of mono 16 kHz 16-bit PCM. The prepared smoke streams its first **30 seconds**, with Japanese language hints and Spanish one-way translation. Source PCM hash, configuration and estimates are in `plan.json`.

From the repository root:

```powershell
& 'backend/.venv/Scripts/python.exe' scripts/trials/soniox_trial.py
```

This command only prepares a plan. Once `SONIOX_API_KEY` is configured locally in the process environment or the workspace `.env`, the explicit execution command is:

```powershell
& 'backend/.venv/Scripts/python.exe' scripts/trials/soniox_trial.py --execute-cloud
```

Do not paste the key into chat. The script redacts keys in responses, never stores its authenticated request, stops on an unsuccessful clip and has no automatic paid retries. Production settings are unchanged.

The hard cap is **120 seconds of requested audio across clips**. Each network session has at most 30 additional seconds for finalization, and the endpoint may charge for streaming session duration. The script does not enforce an exact monetary limit or contact account/billing endpoints.

## Documentation verified live

- [Models](https://soniox.com/docs/stt/models): `stt-rt-v5` is active, introduced June 16, 2026.
- [Supported languages](https://soniox.com/docs/stt/concepts/supported-languages): Japanese `ja` and Spanish `es`; translation supports any pair of listed languages.
- [WebSocket protocol](https://soniox.com/docs/api-reference/stt/websocket-api): PCM configuration, finalized tokens and end-of-stream response.
- [Real-time translation](https://soniox.com/docs/translation/stt-translation/rt-translation): original tokens carry audio timestamps; translated tokens have no timestamps or one-to-one source mapping.
- [API pricing](https://soniox.com/pricing): real-time audio input $2 per million tokens; text input/output $4 per million tokens. Published usage references are about 30,000 audio tokens/hour and 15,000 speech-output tokens/hour.

Assuming another 15,000 Spanish output tokens/hour yields about **$0.18/hour**, or **$0.0015 for 30 seconds of audio**. This is an inference from token rates, not a fixed price. Output density, pauses, context, finalization time and billable session duration can change the actual amount.

## Offline verification only

`offline-verification.json` records checks of frame size and 100 ms pacing, the empty text end signal, final/provisional token handling, source timestamp latency, absent translated timestamps, secret redaction, the missing-key network guard and the audio cap. The script passes Ruff and compiles.

These checks validate the harness, **not Soniox accuracy or latency**. Real runs save sanitized received events plus original and translated texts. Source final-token latency is measured from token audio end to receipt; translated first-token elapsed time is a startup measurement. There is no reference accuracy score, sentence translation latency or application/browser validation yet.
