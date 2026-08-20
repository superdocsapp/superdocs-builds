export type Evidence={id:string; page:string; printedPage?:string; quote:string; included:boolean; kind:string; reason:string; bbox?:string; nativeText?:string; conflict?:string};
export const initial:Evidence[]=[
 {id:'SAFE-001',page:'PDF p. 17',printedPage:'4-1',quote:'Isolate electrical and pneumatic energy before clearing a jam.',included:true,kind:'safety',reason:'safety keyword sweep + adjacent-page expansion',bbox:'71,220,511,248',nativeText:'WARNING: Isolate electrical and pneumatic energy before clearing a jam.'},
 {id:'STEP-001',page:'PDF p. 18',printedPage:'4-2',quote:'Stop the infeed.',included:true,kind:'procedure',reason:'exact task-term search',bbox:'71,140,300,160',nativeText:'1. Stop the infeed.'},
 {id:'SPEC-001',page:'PDF p. 53',printedPage:'4-37',quote:'24 N·m ± 2 N·m',included:true,kind:'specification',reason:'specification sweep',bbox:'71,220,511,248',nativeText:'Guard fastener torque: 24 N·m ± 2 N·m.',conflict:'Decoy value exists for a different operating condition.'},
];
