class BackgroundTaskResponse {
  constructor(id) {
    this.error = false;
    this.id = id;
    this.payload = null;
    this.success = false;
  }

  pass(payload) {
    this.error = false;
    this.payload = payload;
    this.success = true;
  }

  fail(payload) {
    this.error = true;
    this.payload = payload;
    this.success = false;
  }
}

export default class BackgroundTask {
  constructor() {
    self.addEventListener("message", (e) => {
      const { id, taskName, parameters } = e.data;
      const response = new BackgroundTaskResponse(id);
      if (this.taskExists(taskName)) {
        try {
          response.pass(this[taskName](...parameters));

        } catch(err) {
          response.fail(err);
        }

        self.postMessage(response);

      } else {
        throw new BackgroundTask.Error(taskName, this.constructor.name);
      }
    });
  }

  taskExists(taskName) {
    return (taskName in this) && (typeof this[taskName] === "function");
  }
}

BackgroundTask.Error = class extends Error {
  constructor(taskName, taskHandler) {
    super(`Background task "${ taskName }" not found in "${ taskHandler }" controller`);
    this.name = "BackgroundTask Error";
  }
}
