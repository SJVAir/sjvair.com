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
      console.log("Background task response received")
      const { id, error, payload, success } = msg.data;

      if (success && this.resolvers.has(id)) {
        console.log("Background task success")
        this.resolvers.get(id)!(payload);

      } else if (error && this.rejectors.has(id)) {
        console.log("Background task failed")
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
    const task = new BackgroundTask<T>(++this.globalTaskID, taskName, parameters);

    console.log("running task: ", task)
    console.log("worker: ", this.worker)
    return new Promise((resolve, reject) => {
      this.resolvers.set(task.id, resolve);
      this.rejectors.set(task.id, reject);
      this.worker.postMessage(task);
    }) as ReturnType<T[K]>;
  }
}

//export default abstract class BackgroundTaskClient {
//  static worker: Worker;
//
//  globalTaskID: number = 0;
//  resolvers: Map<number, (value: unknown) => void> = new Map();
//  rejectors: Map<number, (reason: any) => void> = new Map();
//  worker: Worker;
//
//  constructor() {
//    const builder = this.constructor as typeof BackgroundTaskClient;
//    this.worker = builder.worker;
//
//    this.worker.onmessage = (msg) => {
//      const { id, error, payload, success } = msg.data;
//
//      if (success && this.resolvers.has(id)) {
//        this.resolvers.get(id)!(payload);
//
//      } else if (error) {
//        this.rejectors.get(id)!(payload);
//      }
//      
//      // purge event callbacks
//      this.resolvers.delete(id);
//      this.rejectors.delete(id);
//    }
//  }
//
//  run(taskName: string, ...parameters: Array<unknown>) {
//    if (taskName in this.constructor)
//    const task = new BackgroundTask(this.globalTaskID++, taskName, parameters);
//
//    return new Promise((resolve, reject) => {
//      this.resolvers.set(task.id, resolve);
//      this.rejectors.set(task.id, reject);
//      this.worker.postMessage(task);
//    });
//  }
//}
