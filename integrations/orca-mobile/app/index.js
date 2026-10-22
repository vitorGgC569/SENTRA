import {Buffer} from 'buffer';
globalThis.Buffer=Buffer;
if(!globalThis.atob)globalThis.atob=value=>Buffer.from(value,'base64').toString('binary');
if(!globalThis.btoa)globalThis.btoa=value=>Buffer.from(value,'binary').toString('base64');
import {registerRootComponent} from 'expo';
import App from './App';
registerRootComponent(App);
