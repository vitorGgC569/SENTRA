/** SENTRA application contract v1, shared by Canvas presentation and mobile. */
export const APPLICATION_PROTOCOL_VERSION=1 as const;
export type WorkspaceScope={project_id:string;space_id:string;dot_id:string};
export type PairedScope=WorkspaceScope&{actions:string[]};
export type ReceiptStage='accepted'|'delivered'|'observing'|'completed'|'failed'|'cancelled'|'uncertain'|'unknown';
export type Receipt={stage:ReceiptStage;source_state:string;completed:boolean;requires_reconciliation:boolean;automatic_retry:false;operation_id?:string;receipt_id?:string};
export type WorkspaceTerminal={id:string;workspace_id:string;name:string;shell:string;status:string;dot_id?:string;host_id:string;tool?:string};
export type WorkspaceInventory=WorkspaceScope&{protocol_version:1;layout_scope:string;host:{id:string;label:string;kind:'local'};resources:{terminals:WorkspaceTerminal[]};graph:Record<string,unknown>;authority:'sentra-control-plane';restoration_creates_resources:false};
export type OperationRequest=WorkspaceScope&{action:string;request_key?:string;conversation_id?:string;[key:string]:unknown};
export type EventCursor={protocol_version:1;resource_id:string;after_sequence:number;gap:boolean};
export type WorkspaceIntentSelector={action:string;request_key:string;fingerprint:string;conversation_id?:string};
export type WorkspaceRequestStatus={found:boolean;resolved:boolean;request_key:string;automatic_retry:false;may_resend:false;receipt:Receipt;operation?:Record<string,unknown>;result?:Record<string,unknown>};
export type ServiceCapability={id:string;available:boolean;reason?:string;actions:readonly string[]};
export type ServiceAdapter={inventory:(scope:WorkspaceScope)=>Promise<WorkspaceInventory>;request:(intent:OperationRequest)=>Promise<unknown>};
export type TerminalOutputFrame={protocol_version:1;terminal_id:string;start:number;cursor:number;text:string;
 has_more:boolean;truncated:boolean;read_only:true;automatic_input_replay:false;status:string;
 process_live?:boolean;recoverable?:boolean;runtime_id?:string;geometry_sequence?:number;checkpoint_supported?:boolean};
