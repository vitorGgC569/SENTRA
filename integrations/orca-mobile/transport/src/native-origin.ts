// React Native otherwise synthesizes an HTTP Origin, just like a browser.
// Browser WebSocket callers cannot override Origin with this native marker.
// This only selects the native transport; E2EE identity and scoped credentials
// remain mandatory and are not replaced by the marker.
export const NATIVE_MOBILE_ORIGIN='sentra-mobile://native';
export function allowedMobileOrigin(origin:unknown){
 return origin===undefined||origin===NATIVE_MOBILE_ORIGIN;
}
