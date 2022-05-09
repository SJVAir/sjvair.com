import type { Monitor } from "../models";
import type { IMonitorVisibility } from "../types";

export class MonitorVisibility implements IMonitorVisibility {
  SJVAirPurple: boolean = true;
  SJVAirInactive: boolean = false; // Currently unused in project, do we need?
  SJVAirBAM: boolean = true;
  PurpleAir: boolean = true;
  PurpleAirInside: boolean = false;
  AirNow: boolean = true;
  displayInactive: boolean = false;

  isVisible(m: Monitor): boolean {
    // showSJVAirPurple
    // showSJVAirInactive
    // showSJVAirBAM
    // showPurpleAir
    // showPurpleAirInside
    // showAirNow

    if(!this.displayInactive && !m.data.is_active){
      return false;
    }

    if(m.data.device == 'PurpleAir') {
      return m.data.is_sjvair 
        ? this.SJVAirPurple
        : this.PurpleAir && (this.PurpleAirInside || m.data.location == 'outside');

    } else if (m.data.device == 'BAM1022'){
      return this.SJVAirBAM;

    }  else if (m.data.device == 'AirNow'){
      return this.AirNow;
    }
    return false;
  }
}
