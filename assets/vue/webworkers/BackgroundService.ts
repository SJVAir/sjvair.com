import { BackgroundTask } from "./BackgroundServiceClient";
import type { IBackgroundService } from "../types";

export class BackgroundTaskResponse {
  error: boolean = false;
  id:number ;
  payload: unknown = null;
  success: boolean = false;

  constructor(taskId: number) {
    this.id = taskId;
  }

  pass(payload: unknown) {
    this.error = false;
    this.payload = payload;
    this.success = true;
  }

  fail(payload: unknown) {
    this.error = true;
    this.payload = payload;
    this.success = false;
  }
}

class BackgroundTaskError extends Error {
  constructor(taskName: string, taskHandler: string) {
    super(`Background task "${ taskName }" not found in "${ taskHandler }" controller`);
    this.name = "BackgroundTask Error";
  }
}

export class BackgroundService {
  service: IBackgroundService;

  constructor(s: IBackgroundService) {
    this.service = s;

    self.addEventListener("message", async (e: MessageEvent<BackgroundTask<IBackgroundService>>) => {
      const { id, taskName, parameters } = e.data;
      const response = new BackgroundTaskResponse(id);

      if (taskName in this.service && typeof this.service[taskName] === "function") {
        await this.service[taskName](...parameters)
          .then((result: any) => response.pass(result))
          .catch((error: any) => response.fail(error))
        //try {
        //  response.pass(await builder[taskName](...parameters));

        //} catch(err) {
        //  response.fail(err);
        //}

        //self.postMessage(response);

      } else {
        response.fail(new BackgroundTaskError(taskName as string, this.constructor.name))
      }
      self.postMessage(response);
    });
  }
}

//function serviceCall<K extends keyof typeof MonitorService>(input: K, parameters: Array<any>): typeof MonitorService[K] {
//    return MonitorService[input](...parameters);
//}
//
//self.addEventListener("message", async (e) => {
//  const { id, taskName, parameters } = e.data;
//  const response = new BackgroundTaskResponse(id);
//  if (taskName in MonitorService) {
//      const task = serviceCall(taskName);
//      response.pass(await task(...parameters));
//    try {
//
//    } catch(err) {
//      response.fail(err);
//    }
//
//    self.postMessage(response);
//
//  } else {
//    throw new BackgroundTaskError(taskName, this.constructor.name);
//  }
//});

//export default class BackgroundTask {
//  constructor() {
//    self.addEventListener("message", (e) => {
//      const { id, taskName, parameters } = e.data;
//      const response = new BackgroundTaskResponse(id);
//      if (this.taskExists(taskName)) {
//        try {
//          response.pass(this[taskName](...parameters));
//
//        } catch(err) {
//          response.fail(err);
//        }
//
//        self.postMessage(response);
//
//      } else {
//        throw new BackgroundTaskError(taskName, this.constructor.name);
//      }
//    });
//  }
//
//  taskExists(taskName: string) {
//    return (taskName in this) && (typeof this[taskName] === "function");
//  }
//}
