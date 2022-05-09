import { BackgroundServiceClient } from "../webworkers/BackgroundServiceClient";
import D3BackgroundService from "./D3Background?worker";
import type { ID3BackgroundService } from "../types";

export class D3Service extends BackgroundServiceClient<ID3BackgroundService> {
  static instance: D3Service;

  constructor() {
    if (D3Service.instance) {
      return D3Service.instance;
    }

    super(new D3BackgroundService());

    D3Service.instance = this;
  }

  async updateLastActiveLimit(limit: any) {
    return await this.run("updateLastActiveLimit", limit);
  }

  async computeSegments(data: Array<any>, isNext?: (prev: any, curr: any) => boolean): Promise<{ gaps: Array<any>, segments: any }> {
    return await this.run("computeSegments", data, isNext);
  }
  
  async lineDefined(dataPoint: any) {
    return await this.run("lineDefined", dataPoint);
  }
  
}
