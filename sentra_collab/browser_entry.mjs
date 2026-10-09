/** One dependency graph prevents incompatible duplicate Yjs constructors. */
import * as Y from 'yjs';
import {HocuspocusProvider} from '@hocuspocus/provider';
globalThis.SentraCollabRuntime=Object.freeze({Y,HocuspocusProvider});
