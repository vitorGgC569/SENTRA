import type {WorkspaceScope,WorkspaceInventory} from '../../../../integrations/orca-mobile/transport/src/contracts';
export type {WorkspaceScope,Receipt,ServiceAdapter,ServiceCapability,EventCursor} from '../../../../integrations/orca-mobile/transport/src/contracts';
export type {WorkspaceIntentSelector,WorkspaceRequestStatus} from '../../../../integrations/orca-mobile/transport/src/contracts';
export type PaneKind = 'map'|'terminals'|'files'|'review'|'browser'|'computer'|'activity';
export type LayoutNode = {type:'leaf';groupId:string}|{type:'split';direction:'horizontal'|'vertical';ratio:number;first:LayoutNode;second:LayoutNode};
export type WorkspaceTab = {id:string;kind:PaneKind;resourceId?:string;dotId?:string;label?:string};
export interface WorkspaceAdapter {
 inventory(scope:WorkspaceScope):Promise<WorkspaceInventory>;
 request(action:string,fields:Record<string,unknown>):Promise<unknown>;
}
