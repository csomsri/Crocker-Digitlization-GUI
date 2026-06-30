/**
    Author(s): Chotrawit Benko (L0R3ST)
    Description:
        Main loop for Graphics / Engine Pipeline
    Progress and Comments:
        OpenGL 4.6 render pipeline
*/

#pragma once

class Engine {
public:
    Engine();

    void Initialize();
    void Update();
    void Render();
    void Run();
};
