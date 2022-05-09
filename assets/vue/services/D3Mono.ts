import { D3BackgroundService } from "./D3Background";

export class D3ServiceMono {
  static instance: D3ServiceMono;

  constructor() {
    if (D3ServiceMono.instance) {
      return D3ServiceMono.instance;
    }


    D3ServiceMono.instance = this;
  }

  async updateLastActiveLimit(limit: any) {
    return await D3BackgroundService.updateLastActiveLimit(limit);
  }

  computeSegments(data: Array<any>, isNext?: (prev: any, curr: any) => boolean): { gaps: Array<any>, segments: any } {
    return D3BackgroundService.computeSegments(data, isNext);
  }
  
  lineDefined(dataPoint: any) {
    return D3BackgroundService.lineDefined(dataPoint);
  }
  
}
