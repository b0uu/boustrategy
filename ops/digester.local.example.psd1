@{
    # Copy this file to digester.local.psd1 and replace the placeholders.
    # digester.local.psd1 is gitignored because the webhook URL is a secret.
    # Every scheduled wrapper (digester, prepare, review poller) reads it.
    DiscordWebhookUrl = "https://discord.com/api/webhooks/REPLACE_ME"

    # The bot's own Codex identity. Keep it separate from your personal
    # ~/.codex so the trading account and its usage never mix with yours.
    CodexExe = "codex"
    CodexHome = "C:\Users\Administrator\.codex-boustrategy"

    # Tedious, high-volume work: X digests.
    DigestModel = "gpt-5.6-luna"
    DigestReasoningEffort = "low"

    # One-off investment reviews. The runtime passes only the model; its
    # reasoning effort comes from the Codex default because user config is
    # ignored during authoring.
    ReviewModel = "gpt-5.6-sol"

    # Broker sessions: cheap account/quote reads, careful execution.
    CollectorModel = "gpt-5.6-luna"
    ExecutionModel = "gpt-5.6-sol"
    LiveProfile = "codex"
}
