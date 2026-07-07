# From Labview to ZeroMQ
How the data will be transported is within the App/UI Layer:

There will be a sender and server continuously receiveing and sending messages
```cpp
ZMQServer server("tcp://0.0.0.0:5555");
ZMQSender sender("tcp://*:5566");

server.Start();
sender.Bind();
```