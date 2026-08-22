/**
 * @file Camera.hpp
 * 
 * @brief Implementation of Camera that will be used
 *        for future 3D Visualization
 * 
 * Responsible for changing and moving a movable viewport
 * 
 * @author Chotrawit Benko
 * @date 2026-08-22
 */
#include "Engine/Render/Camera.hpp"

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

/**
 * @brief Grab keyboard output to change position of Camera
 * 
 * @param direction an enumeration of possible position of camera
 * @param delta_time counting frames and change of time
 */
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

/**
 * @brief Turn mouse movement into zoom or drag
 * 
 * 
 * @param xoffset x axis offset 
 * @param xoffset y axis offset
 * @param constrain_pitch boolean to decide if to constrain the pitch
 */
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
