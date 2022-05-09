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
