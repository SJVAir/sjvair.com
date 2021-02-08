import Axios from 'axios';

const extractData = data => {
  data = JSON.parse(data);
  return ("data" in data) ? data.data : data;
};

export default Axios.create({
  baseURL: '/api/1.0/',
  transformResponse: [ extractData ]
});
