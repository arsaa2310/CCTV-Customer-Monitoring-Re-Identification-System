# CCTV Customer Monitoring & Re-Identification System

An AI-powered CCTV monitoring system designed to detect, track, and re-identify customers in real-time video streams.

The system combines computer vision and customer re-identification techniques to maintain a consistent identity for the same person across video frames and potentially across multiple appearances. This enables the system to monitor customer presence, movement, visit frequency, and basic behavioral patterns without relying solely on frame-by-frame detection.

## Key Features

- Real-time customer detection from CCTV streams
- Multi-object tracking
- Customer re-identification across video frames
- Customer counting and occupancy monitoring
- Entry and exit monitoring
- Customer visit/session tracking
- Customer trajectory visualization
- Detection and tracking history
- Customer appearance database
- Real-time monitoring dashboard
- CCTV/RTSP stream integration
- Event and activity logging

## AI / Computer Vision Pipeline

```text
CCTV / RTSP Stream
        ↓
Video Frame Processing
        ↓
Person / Customer Detection
        ↓
Multi-Object Tracking
        ↓
Person Re-Identification
        ↓
Customer Identity / Track ID
        ↓
Event & Movement Logging
        ↓
Database
        ↓
Analytics / Dashboard
```

## Example Use Cases

The system can be used for:

- Customer traffic monitoring
- Store occupancy monitoring
- Customer flow analysis
- Visit frequency analysis
- Queue and waiting-time analysis
- Store layout analysis
- Customer movement analysis
- CCTV-based operational analytics

## Technology Stack

### Computer Vision

- Python
- OpenCV
- YOLO
- Object Tracking
- Person Re-Identification

### Backend & Data

- Python
- PostgreSQL
- REST API
- Docker

### Monitoring

- Streamlit / Web Dashboard
- Real-time video visualization
- Customer tracking visualization
- Analytics dashboard

## Example Analytics

The system can generate information such as:

- Number of customers currently inside the monitored area
- Number of unique customer tracks
- Customer entry and exit times
- Estimated visit duration
- Customer movement trajectories
- Frequently visited areas
- Returning customer patterns
- Customer traffic over time

## Project Goal

The primary goal of this project is to demonstrate how computer vision, object tracking, and re-identification can be combined with data engineering and analytics to transform CCTV video streams into structured customer activity data.

Instead of treating CCTV footage only as video, this project converts video observations into structured events that can be analyzed for operational and business intelligence purposes.

## Privacy Considerations

This project focuses on computer-vision-based tracking and re-identification within a controlled environment. Re-identification IDs are treated as system-generated identifiers rather than real-world identities.

For production deployment, appropriate consent, data-retention policies, access controls, and applicable privacy regulations should be considered.
