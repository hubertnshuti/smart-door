"""
Face recognition engine built on InsightFace.

Two faces are the same person if their embeddings have high cosine similarity.
"""
import numpy as np
from insightface.app import FaceAnalysis
import config


class FaceEngine:
    def __init__(self):
        self.app = FaceAnalysis(
            name=config.FACE_MODEL,
            providers=["CPUExecutionProvider"],
        )
        self.app.prepare(ctx_id=0, det_size=(320, 320))

    def get_faces(self, frame_bgr):
        return self.app.get(frame_bgr)

    @staticmethod
    def cosine_similarity(a, b):
        a = a / (np.linalg.norm(a) + 1e-8)
        b = b / (np.linalg.norm(b) + 1e-8)
        return float(np.dot(a, b))

    def match(self, embedding, known_faces):
        """
        Compare one embedding against all known faces.

        known_faces: list of (id, name, type, embedding_array)
                     where type is 'student' or 'staff'

        Returns dict {id, name, type, score} on match, or None if no match.
        """
        best_id   = None
        best_name = None
        best_type = None
        best_score = -1.0

        for pid, name, ptype, known_emb in known_faces:
            score = self.cosine_similarity(embedding, known_emb)
            if score > best_score:
                best_score = score
                best_id    = pid
                best_name  = name
                best_type  = ptype

        if best_score >= config.MATCH_THRESHOLD:
            return {"id": best_id, "name": best_name,
                    "type": best_type, "score": best_score}
        return None

    def largest_face(self, faces):
        if not faces:
            return None
        return max(
            faces,
            key=lambda f: (f.bbox[2] - f.bbox[0]) * (f.bbox[3] - f.bbox[1]),
        )
