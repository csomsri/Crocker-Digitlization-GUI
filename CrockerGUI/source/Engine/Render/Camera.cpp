#include "Engine/Engine/Render/Camera.hpp"

#include <glm/gtc/matrix_transform.hpp>

#include <algorithm>
#include <cmath>

Camera::Camera(glm::vec3 position, glm::vec3 up, float yaw, float pitch)
    : position(position),
      front(0.0f, 0.0f, -1.0f),
      up(up),
      right(1.0f, 0.0f, 0.0f),
      world_up(up),
      yaw(yaw),
      pitch(pitch),
      movement_speed(2.5f),
      mouse_sensitivity(0.1f),
      zoom(45.0f) {
    UpdateCameraVectors();
}

glm::mat4 Camera::GetViewMatrix() const {
    return glm::lookAt(position, position + front, up);
}

void Camera::ProcessKeyboard(CameraMovement direction, float delta_time) {
    const float velocity = movement_speed * delta_time;
    switch (direction) {
        case CameraMovement::Forward:  position += front * velocity; break;
        case CameraMovement::Backward: position -= front * velocity; break;
        case CameraMovement::Left:     position -= right * velocity; break;
        case CameraMovement::Right:    position += right * velocity; break;
        case CameraMovement::Up:       position += world_up * velocity; break;
        case CameraMovement::Down:     position -= world_up * velocity; break;
    }
}

void Camera::ProcessMouseMovement(float xoffset, float yoffset, bool constrain_pitch) {
    yaw += xoffset * mouse_sensitivity;
    pitch += yoffset * mouse_sensitivity;
    if (constrain_pitch) {
        pitch = std::clamp(pitch, -89.0f, 89.0f);
    }
    UpdateCameraVectors();
}

float Camera::GetZoom() const { return zoom; }
glm::vec3 Camera::GetPosition() const { return position; }

void Camera::UpdateCameraVectors() {
    glm::vec3 direction;
    direction.x = std::cos(glm::radians(yaw)) * std::cos(glm::radians(pitch));
    direction.y = std::sin(glm::radians(pitch));
    direction.z = std::sin(glm::radians(yaw)) * std::cos(glm::radians(pitch));

    front = glm::normalize(direction);
    right = glm::normalize(glm::cross(front, world_up));
    up = glm::normalize(glm::cross(right, front));
}
