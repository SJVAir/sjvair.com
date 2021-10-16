class BackgroundTask {
  constructor(id, taskName, parameters) {
    this.id = id;
    this.parameters = parameters;
    this.taskName = taskName;
  }
}

export default class BackgroundTaskClient {
  constructor(worker) {
    this.globalTaskID = 0
    this.resolvers = new Map();
    this.rejectors = new Map();
    this.worker = worker;
    this.worker.onmessage = (msg) => {
      const { id, error, payload, success } = msg.data;

      if (success && this.resolvers.has(id)) {
        this.resolvers.get(id)(payload);

      } else if (error) {
        this.rejectors.get(id)(payload);
      }
      
      // purge event callbacks
      this.resolvers.delete(id);
      this.rejectors.delete(id);
    }
  }

  run(taskName, ...parameters) {
    const task = new BackgroundTask(this.globalTaskID++, taskName, parameters);

    return new Promise((resolve, reject) => {
      this.resolvers.set(task.id, resolve);
      this.rejectors.set(task.id, reject);
      this.worker.postMessage(task);
    });
  }
}
