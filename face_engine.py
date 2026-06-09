"""
Face recognition engine built on InsightFace.

InsightFace gives each detected face a 512-dimensional "embedding" vector.
Two faces are the same person if their embeddings point in nearly the same
direction (high cosine similarity).
"""
import numpy as np
from insightface.app import FaceAnalysis
import config


class FaceEngine:
    def __init__(self):
        # CPUExecutionProvider because the Pi has no GPU.
        # buffalo_sc is the smallest bundle -> fastest on a Pi Zero 2 W.
        self.app = FaceAnalysis(
            name=config.FACE_MODEL,
            providers=["CPUExecutionProvider"],
        )
        # det_size smaller = faster but misses small/distant faces.
        self.app.prepare(ctx_id=0, det_size=(320, 320))

    def get_faces(self, frame_bgr):
        """Return list of detected face objects from a BGR image (OpenCV format)."""
        return self.app.get(frame_bgr)

    @staticmethod
    def cosine_similarity(a, b):
        a = a / (np.linalg.norm(a) + 1e-8)
        b = b / (np.linalg.norm(b) + 1e-8)
        return float(np.dot(a, b))

    def match(self, embedding, known_users):
        """
        Compare one embedding against all known users.
        known_users: list of (id, name, embedding, image)
        Returns (name, score) of best match, or (None, best_score) if no match.
        """
        best_name = None
        best_score = -1.0
        for _id, name, known_emb, _img in known_users:
            score = self.cosine_similarity(embedding, known_emb)
            if score > best_score:
                best_score = score
                best_name = name
        if best_score >= config.MATCH_THRESHOLD:
            return best_name, best_score
        return None, best_score

    def largest_face(self, faces):
        """Pick the biggest face in the frame (the person closest to the door)."""
        if not faces:
            return None
        return max(
            faces,
            key=lambda f: (f.bbox[2] - f.bbox[0]) * (f.bbox[3] - f.bbox[1]),
        )
