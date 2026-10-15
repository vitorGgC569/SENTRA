// A broker restart invalidates the previous bearer. Navigation is owned by
// the trusted native bridge, not by a failed API request. No POST is replayed.
export function createNativeAuthRecovery({cooldownMs = 7000, now = () => Date.now(), onFailure = () => {}} = {}) {
  let pending = false;
  let nextAllowed = 0;
  return function requestReauthorization(native) {
    if (typeof native?.reauthorize !== 'function') return false;
    const timestamp = now();
    if (pending || timestamp < nextAllowed) return false;
    pending = true;
    nextAllowed = timestamp + cooldownMs;
    // Do not await navigation before failing the original request: the caller
    // must not mistakenly treat an unknown mutation as successfully delivered.
    Promise.resolve().then(() => native.reauthorize())
      .then(result => {
        if (!result || result.authenticated_owner !== true) throw Error('Native owner not confirmed');
      })
      .catch(() => {
        // Expose a single useful next step rather than resurfacing every 401.
        // Do not leak secrets, retry the request or alter any receipt.
        onFailure();
      })
      .finally(() => { pending = false; });
    return true;
  };
}
