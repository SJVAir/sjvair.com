import type { BackgroundTaskResponse } from "./BackgroundService";
import type { IBackgroundService } from "../types";

export class BackgroundTask<T extends IBackgroundService> {
  id: number;
  parameters: Parameters<T[keyof T]>;
  taskName: keyof T;

  constructor(
    id: BackgroundTask<T>["id"],
    taskName: BackgroundTask<T>["taskName"],
    parameters: BackgroundTask<T>["parameters"]
  ) {
    this.id = id;
    this.parameters = parameters;
    this.taskName = taskName;
  }
}

export class BackgroundServiceClient<T extends IBackgroundService> {
  private globalTaskID = 0
  private resolvers: Map<number, (value: unknown) => void> = new Map();
  private rejectors: Map<number, (reason?: any) => void> = new Map();
  private worker: Worker;

  constructor(w: Worker) {
    this.worker = w;

    this.worker.onmessageerror = (ev: MessageEvent<any>) => console.error("worker failed: ", ev);
    this.worker.onmessage = (msg: MessageEvent<BackgroundTaskResponse>) => {
      const { id, error, payload, success } = msg.data;
      console.log(`Completed task with id ${ id }`);

      if (success && this.resolvers.has(id)) {
        this.resolvers.get(id)!(payload);

      } else if (error && this.rejectors.has(id)) {
        this.rejectors.get(id)!(payload);

      } else {
        console.error(`Unknown response from background service "${this.constructor.name}"`)
      }
      
      // purge event callbacks
      this.resolvers.delete(id);
      this.rejectors.delete(id);
    }
  }


  run<K extends keyof T>(taskName: K, ...parameters: Parameters<T[K]>): Promise<Awaited<ReturnType<T[K]>>> {
    const task = new BackgroundTask<T>(++this.globalTaskID, taskName, JSON.parse(JSON.stringify(parameters)));
    console.log("before: ", task);

    return new Promise((resolve, reject) => {
      this.resolvers.set(task.id, resolve);
      this.rejectors.set(task.id, reject);
      this.worker.postMessage(task);
    }) as ReturnType<T[K]>;
  }
}
