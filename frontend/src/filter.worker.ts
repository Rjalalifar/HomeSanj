import type { Inventory } from './api';
import type { SearchState } from './contracts.generated';
import { filterInventory,sortRows } from './filter';
let inventory:Inventory|null=null;
self.onmessage=(event:MessageEvent<{inventory?:Inventory;state?:SearchState;revision:number;limit:number}>)=>{
  if(event.data.inventory) inventory=event.data.inventory;
  if(!inventory||!event.data.state) return;
  const start=performance.now(),rows=sortRows(filterInventory(inventory,event.data.state),event.data.state);
  self.postMessage({revision:event.data.revision,count:rows.length,rows:rows.slice(0,event.data.limit),duration_ms:performance.now()-start});
};
