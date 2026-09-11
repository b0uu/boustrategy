# Non-secret settings for the public dashboard launch. Copy to ops\public.local.psd1
# (gitignored) and adjust. Nothing here is a credential: the Discord webhook stays in
# ops\digester.local.psd1, the Cloudflare tunnel credential stays in the cloudflared
# configuration directory, and broker identity stays in ops\live.local.json.
@{
    # Public hostname routed by the named Cloudflare Tunnel. Documentation only; the
    # tunnel's own config.yml is the authority on routing.
    PublicHostname           = "example.com"
    TunnelName               = "example-public"

    # Loopback port of the read-only origin. The server always binds 127.0.0.1.
    PublicPort               = 8380

    # Valuation tick: backstop timeout in seconds (30-600) and the consecutive-failure
    # count that re-alerts after the first failure.
    ValuationTimeoutSeconds  = 480
    ValuationAlertAfter      = 3

    # How long the health check waits for the publisher to catch up with a source change
    # before calling publication stuck.
    PublicationSettleSeconds = 30
}
