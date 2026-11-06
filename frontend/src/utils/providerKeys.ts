/** Provider keys from the browser's key store, in the `provider_keys` shape the backend takes
 *  for runs it makes on the user's behalf (evals, publish gates). Saved flows don't hold them. */
export function browserProviderKeys(resolveApiKey: (provider: string) => string): Record<string, string> {
  return {
    openai: resolveApiKey('openai'), anthropic: resolveApiKey('anthropic'),
    groq: resolveApiKey('groq'), gemini: resolveApiKey('gemini'), mistral: resolveApiKey('mistral'),
  }
}
