/**
 * In-memory browser-side token manager for Google Picker OAuth tokens.
 *
 * Tokens are NEVER persisted to storage or sent to the backend.
 */

/** Safety margin subtracted when checking token validity. */
export const EXPIRY_SKEW_MS = 30_000;

export type PickerTokenResponse = {
  accessToken: string;
  expiresIn: number;
};

export type PickerTokenRequester = (
  prompt: "" | "consent",
) => Promise<PickerTokenResponse>;

export class PickerTokenManager {
  private _token: string | null = null;
  private _expiresAt: number = 0;
  private _hasAuthorized: boolean = false;
  private _requestInFlight: Promise<string> | null = null;

  get currentToken(): string | null {
    return this._token;
  }

  get hasAuthorized(): boolean {
    return this._hasAuthorized;
  }

  /** `"consent"` for the first authorization, `""` afterward. */
  get promptHint(): "" | "consent" {
    return this._hasAuthorized ? "" : "consent";
  }

  /**
   * Whether a cached token exists and has not yet expired
   * (accounting for {@link EXPIRY_SKEW_MS}).
   */
  hasValidToken(now: number = Date.now()): boolean {
    return this._token !== null && now < this._expiresAt - EXPIRY_SKEW_MS;
  }

  /**
   * Process a GIS `TokenResponse`.
   *
   * @param accessToken  `response.access_token`
   * @param expiresIn    `response.expires_in` (seconds). If the value is
   *                     missing, non-finite, or <= 0 the token is NOT cached
   *                     for reuse — callers may still use `accessToken`
   *                     for the immediate operation.
   * @param now          Overridable clock for testing.
   */
  handleTokenResponse(
    accessToken: string,
    expiresIn: number,
    now: number = Date.now(),
  ): void {
    this._hasAuthorized = true;

    if (
      typeof expiresIn !== "number" ||
      !Number.isFinite(expiresIn) ||
      expiresIn <= 0
    ) {
      this._token = null;
      this._expiresAt = 0;
      return;
    }

    this._token = accessToken;
    this._expiresAt = now + expiresIn * 1000;
  }

  /**
   * Return the still-valid browser token, or request and cache a replacement.
   *
   * Keeping this decision here ensures every Picker entry point uses the same
   * prompt transition: consent initially, then a silent prompt after expiry.
   */
  async getToken(requestToken: PickerTokenRequester): Promise<string> {
    if (this.hasValidToken()) return this._token!;

    if (this._requestInFlight) return this._requestInFlight;

    const request = requestToken(this.promptHint).then((response) => {
      this.handleTokenResponse(response.accessToken, response.expiresIn);
      return response.accessToken;
    });
    this._requestInFlight = request;
    void request.then(
      () => {
        if (this._requestInFlight === request) this._requestInFlight = null;
      },
      () => {
        if (this._requestInFlight === request) this._requestInFlight = null;
      },
    );
    return request;
  }
}

/**
 * One memory-only token manager for the loaded browser application.
 *
 * This intentionally lives outside React so unmounting/remounting a source
 * chooser (for example through Change source) cannot discard a valid Picker
 * token. It is recreated on a full page load and is never persisted.
 */
export const browserPickerTokenManager = new PickerTokenManager();
